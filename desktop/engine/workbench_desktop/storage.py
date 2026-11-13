# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Local storage for MEL import recipes and file revisions (one SQLite file).

Desktop: <app data dir>/workbench.db, passed by the shell as --data-dir.
Each recipe is one JSON document, so saving it is a single atomic write.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from workbench_core.keylists.cable_types import CableType, CableTypeList, default_cable_types, fill_insulation
from workbench_core.deliverables import Deliverable, next_letter
from workbench_core.deliverables import Revision as IssuedRevision
from workbench_core.deliverables import RevisionInfo as IssueInfo
from workbench_core.keylists.plc import PlcList, from_registers
from workbench_core.keylists.distribution_panels import DistributionPanelList
from workbench_core.keylists.instrument_runsheet import InstrumentRunsheet
from workbench_core.keylists.drawing_list import DocumentList, DrawingList
from workbench_core.keylists.enums import ProjectEnums, default_enums
from workbench_core.keylists.loadgen import LISTS
from workbench_core.keylists.loadlist import FACTOR_FIELDS
from workbench_core.mel.load_fields import FieldChange, LoadFields, default_load_fields
from workbench_core.keylists.master_columns import ColumnChange, MasterColumns, default_master_columns, rename_in, rewrite_rows
from workbench_core.keylists import (
    EEL_SOURCE,
    KEPT,
    PRIMARY_SUPPLY,
    AttachedFile,
    EelList,
    EquipmentCodeList,
    EquipmentPackageList,
    InstrumentCodeList,
    LoadListRow,
    LoadTypeList,
    PlantAreaList,
    apply_auto,
    apply_auto_supply,
    panel_index,
    supply_loop,
)
from workbench_core.mel import Recipe, Revision
from workbench_core.mel.models import is_load_target
from workbench_core.refdata import EnumList, RefRow, RefTable, RefTree, RefValidationError, name_key
from workbench_core.mel.models import RevisionInfo
from workbench_core.symbols import Drawing, Library, PageOverride, PageResult, PageReview, RunInfo, Template, Word
from workbench_core.generators.editable import BuildInfo, BuildRecord, GenRecord, GenSummary, summarise
from workbench_core.generators.hardware import Catalogue, Hardware, default_catalogue
from workbench_core.generators.models import BuildResult, Generator, RefTable as GenTable
from workbench_core.generators.xlsx_import import ImportReport

from . import audit

SCHEMA = """
CREATE TABLE IF NOT EXISTS recipes (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    target TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS revisions (
    id TEXT PRIMARY KEY,
    recipe_id TEXT NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    rev INTEGER NOT NULL,
    info TEXT NOT NULL,
    data TEXT NOT NULL,
    UNIQUE (recipe_id, rev)
);
-- Reference data. Lists and tables share one name space (name_key is unique).
CREATE TABLE IF NOT EXISTS ref_names (
    name_key TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    object_id TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS ref_enums (
    id TEXT PRIMARY KEY,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ref_trees (
    id TEXT PRIMARY KEY,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ref_tables (
    id TEXT PRIMARY KEY,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ref_rows (
    id TEXT PRIMARY KEY,
    table_id TEXT NOT NULL REFERENCES ref_tables(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ref_rows_table ON ref_rows(table_id, seq);
-- Symbol detection. Page renders and words are files under <data dir>/symbols/<drawing id>/.
CREATE TABLE IF NOT EXISTS sym_libraries (
    id TEXT PRIMARY KEY,
    name_key TEXT NOT NULL UNIQUE,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sym_drawings (
    id TEXT PRIMARY KEY,
    library_id TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sym_templates (
    id TEXT PRIMARY KEY,
    library_id TEXT NOT NULL REFERENCES sym_libraries(id) ON DELETE CASCADE,
    priority INTEGER NOT NULL,
    data TEXT NOT NULL,
    image BLOB NOT NULL,
    mask BLOB,
    UNIQUE (library_id, priority)
);
-- What a template cut from a page looked like with its text, and that text's boxes (template
-- pixels): shown in the template editor only. Matching uses sym_templates.image (text erased).
CREATE TABLE IF NOT EXISTS sym_template_views (
    template_id TEXT PRIMARY KEY REFERENCES sym_templates(id) ON DELETE CASCADE,
    image BLOB NOT NULL,
    words TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sym_overrides (
    doc_id TEXT NOT NULL REFERENCES sym_drawings(id) ON DELETE CASCADE,
    page INTEGER NOT NULL,
    template_id TEXT NOT NULL REFERENCES sym_templates(id) ON DELETE CASCADE,
    data TEXT NOT NULL,
    PRIMARY KEY (doc_id, page, template_id)
);
CREATE TABLE IF NOT EXISTS sym_results (
    doc_id TEXT NOT NULL REFERENCES sym_drawings(id) ON DELETE CASCADE,
    page INTEGER NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (doc_id, page)
);
CREATE TABLE IF NOT EXISTS sym_reviews (
    doc_id TEXT NOT NULL REFERENCES sym_drawings(id) ON DELETE CASCADE,
    page INTEGER NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (doc_id, page)
);
CREATE TABLE IF NOT EXISTS sym_runs (
    id TEXT PRIMARY KEY,
    info TEXT NOT NULL,
    sheets TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
-- Deliverable generators: the editable document, its (read-only) lookup tables, and builds.
CREATE TABLE IF NOT EXISTS gen_generators (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    source_file TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    data TEXT NOT NULL,
    report TEXT
);
CREATE TABLE IF NOT EXISTS gen_tables (
    generator_id TEXT NOT NULL REFERENCES gen_generators(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (generator_id, name)
);
CREATE TABLE IF NOT EXISTS gen_builds (
    id TEXT PRIMARY KEY,
    generator_id TEXT NOT NULL REFERENCES gen_generators(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    info TEXT NOT NULL,
    data TEXT NOT NULL,
    UNIQUE (generator_id, seq)
);
-- PLC hardware registers of generators before the PLC List (moved into it once; kept, no longer used).
CREATE TABLE IF NOT EXISTS gen_hardware (
    generator_id TEXT PRIMARY KEY REFERENCES gen_generators(id) ON DELETE CASCADE,
    data TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    data TEXT NOT NULL
);
-- The Load List: every row seen in a MEL/EEL import (by import and key), with its allocations.
CREATE TABLE IF NOT EXISTS load_list (
    recipe_id TEXT NOT NULL,
    row_key TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (recipe_id, row_key)
);
-- Deliverables (issued lists) and their revisions: `data` is the frozen content of a revision.
CREATE TABLE IF NOT EXISTS deliverables (
    id TEXT PRIMARY KEY,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS deliverable_revisions (
    id TEXT PRIMARY KEY,
    deliverable_id TEXT NOT NULL REFERENCES deliverables(id),
    letter TEXT NOT NULL,
    info TEXT NOT NULL,
    data TEXT NOT NULL,
    UNIQUE (deliverable_id, letter)
);
-- Key lists: the project's built-in lists, one JSON document each (id 'plant-areas', ...).
CREATE TABLE IF NOT EXISTS key_lists (
    id TEXT PRIMARY KEY,
    data TEXT NOT NULL
);
"""


def default_data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        return base / "DrawingWorkbench"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "drawing-workbench"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class NotFound(KeyError):
    pass


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA journal_mode = WAL")
        self._db.execute("PRAGMA busy_timeout = 5000")
        self._db.executescript(SCHEMA)
        self._db.executescript(audit.SCHEMA)
        self._keep_load_list_columns()

    def _keep_load_list_columns(self) -> None:
        """Once per project: the Load List deliverable's content became the whole Project Master
        Load List (its cable columns and every field besides its 10 columns). A Load List
        deliverable that showed every column is given those 10 explicitly, so it shows what it
        did and its next revision is not changed by the update."""
        key = "load_list_columns_v2"
        with self._db:
            if self._db.execute("SELECT 1 FROM settings WHERE key = ?", (key,)).fetchone():
                return
            for did, data in self._db.execute("SELECT id, data FROM deliverables").fetchall():
                d = Deliverable.model_validate_json(data)
                if d.type == "Load List" and d.source == "project" and not d.columns:
                    d = d.model_copy(update={"columns": list(LISTS["load_list"].columns)})
                    self._db.execute("UPDATE deliverables SET data = ? WHERE id = ?", (d.model_dump_json(), did))
            self._db.execute("INSERT INTO settings VALUES (?, ?)", (key, "1"))

    # -- change log ------------------------------------------------------------

    def version_of(self, entity: str, record_id: str) -> int:
        with self._lock:
            return audit.version_of(self._db, entity, record_id)

    def audit_entries(self, **filters) -> list[dict]:
        with self._lock:
            return audit.entries(self._db, **filters)

    def audit_users(self) -> list[str]:
        with self._lock:
            return audit.users(self._db)

    # -- the project itself ------------------------------------------------------

    def project_meta(self) -> dict | None:
        """This project's own details (id, name, archived, members, created_at, created_by).
        They live in the project's database so the folder is complete on its own: copy or
        move it and its name, members and history go with it."""
        with self._lock:
            data = audit.data_of(self._db, "settings", "key = ?", ("project",))
        return json.loads(data) if data else None

    def save_project_meta(self, meta: dict, log: bool = True, note: str | None = None) -> None:
        shown = lambda m: m and {k: m[k] for k in ("name", "archived", "members")}  # noqa: E731
        with self._lock, self._db:
            before = audit.data_of(self._db, "settings", "key = ?", ("project",))
            self._db.execute("INSERT INTO settings VALUES ('project', ?) ON CONFLICT(key) DO UPDATE SET "
                             "data = excluded.data", (json.dumps(meta),))
            if log:
                audit.log(self._db, "project", meta["id"], shown(json.loads(before)) if before else None, shown(meta),
                          label=meta["name"], note=note)

    # -- recipes -------------------------------------------------------------

    def list_recipes(self) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT r.id, r.name, r.target, r.updated_at, COUNT(v.id), MAX(v.rev) "
                "FROM recipes r LEFT JOIN revisions v ON v.recipe_id = r.id "
                "GROUP BY r.id ORDER BY r.updated_at DESC").fetchall()
        return [{"id": i, "name": n, "target": t, "updated_at": u, "revisions": c, "latest_rev": m}
                for i, n, t, u, c, m in rows]

    def create_recipe(self, name: str, target: str) -> Recipe:
        recipe = Recipe(id=uuid.uuid4().hex, name=name.strip() or target, target=target, updated_at=_now())
        with self._lock, self._db:
            self._db.execute("INSERT INTO recipes VALUES (?, ?, ?, ?, ?, ?)",
                             (recipe.id, recipe.name, recipe.target, recipe.model_dump_json(),
                              recipe.updated_at.isoformat(), recipe.updated_at.isoformat()))
            audit.log(self._db, "mel_recipe", recipe.id, None, recipe.model_dump_json())
        return recipe

    def get_recipe(self, recipe_id: str) -> Recipe:
        with self._lock:
            row = self._db.execute("SELECT data FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
        if not row:
            raise NotFound(recipe_id)
        return Recipe.model_validate_json(row[0])

    def save_recipe(self, recipe: Recipe) -> Recipe:
        recipe = recipe.model_copy(update={"updated_at": _now()})
        with self._lock, self._db:
            before = audit.data_of(self._db, "recipes", "id = ?", (recipe.id,))
            if before is None:
                raise NotFound(recipe.id)
            self._db.execute("UPDATE recipes SET name = ?, target = ?, data = ?, updated_at = ? WHERE id = ?",
                             (recipe.name, recipe.target, recipe.model_dump_json(),
                              recipe.updated_at.isoformat(), recipe.id))
            audit.log(self._db, "mel_recipe", recipe.id, before, recipe.model_dump_json())
        return recipe

    def delete_recipe(self, recipe_id: str) -> None:
        with self._lock, self._db:
            before = audit.data_of(self._db, "recipes", "id = ?", (recipe_id,))
            self._db.execute("DELETE FROM recipes WHERE id = ?", (recipe_id,))
            if before is not None:
                audit.log(self._db, "mel_recipe", recipe_id, before, None)

    # -- revisions -------------------------------------------------------------

    def add_revision(self, recipe_id: str, file_name: str, source: str, key_header: str,
                     headers_original: list[str], headers: list[str], rows: list[dict[str, str]],
                     warnings: list[str], file_rows: list[int] | None = None) -> RevisionInfo:
        """`file_rows`: each row's data row in the file (the rows may be in another order)."""
        self.get_recipe(recipe_id)  # 404 if missing
        with self._lock, self._db:
            (latest,) = self._db.execute("SELECT COALESCE(MAX(rev), 0) FROM revisions WHERE recipe_id = ?",
                                         (recipe_id,)).fetchone()
            info = RevisionInfo(id=uuid.uuid4().hex, rev=latest + 1, file_name=file_name, source=source,
                                key_header=key_header, num_rows=len(rows), num_cols=len(headers),
                                uploaded_at=_now(), warnings=warnings)
            data = json.dumps({"headers": headers, "headers_original": headers_original, "rows": rows,
                               "file_rows": file_rows or []})
            self._db.execute("INSERT INTO revisions VALUES (?, ?, ?, ?, ?)",
                             (info.id, recipe_id, info.rev, info.model_dump_json(), data))
            self._db.execute("UPDATE recipes SET updated_at = ? WHERE id = ?", (_now().isoformat(), recipe_id))
            # The row data can be large; the log keeps the file's details, not its contents.
            audit.log(self._db, "mel_revision", info.id, None, info.model_dump_json(), parent_id=recipe_id,
                      label=f"Rev {info.rev}: {info.file_name}")
        return info

    def list_revisions(self, recipe_id: str) -> list[RevisionInfo]:
        with self._lock:
            rows = self._db.execute("SELECT info FROM revisions WHERE recipe_id = ? ORDER BY rev DESC",
                                    (recipe_id,)).fetchall()
        return [RevisionInfo.model_validate_json(r[0]) for r in rows]

    def latest_revision(self, recipe_id: str) -> Revision | None:
        """The pipeline always reads the newest revision (PRD 4.2)."""
        with self._lock:
            row = self._db.execute("SELECT info, data FROM revisions WHERE recipe_id = ? ORDER BY rev DESC LIMIT 1",
                                   (recipe_id,)).fetchone()
        if not row:
            return None
        return Revision(**json.loads(row[0]), **json.loads(row[1]))

    def delete_revision(self, recipe_id: str, revision_id: str) -> None:
        with self._lock, self._db:
            before = audit.data_of(self._db, "revisions", "id = ? AND recipe_id = ?", (revision_id, recipe_id), "info")
            self._db.execute("DELETE FROM revisions WHERE id = ? AND recipe_id = ?", (revision_id, recipe_id))
            if before is not None:
                info = json.loads(before)
                audit.log(self._db, "mel_revision", revision_id, info, None, parent_id=recipe_id,
                          label=f"Rev {info.get('rev')}: {info.get('file_name')}")


class RefStore:
    """Lists, tables and rows. Shares the Store's connection and lock."""

    def __init__(self, store: Store):
        self._db = store._db
        self._lock = store._lock

    def _claim_name(self, kind: str, object_id: str, name: str) -> None:
        key = name_key(name)
        row = self._db.execute("SELECT kind, object_id FROM ref_names WHERE name_key = ?", (key,)).fetchone()
        if row and row[1] != object_id:
            kind, other = row
            table = {"enum": "ref_enums", "tree": "ref_trees"}.get(kind, "ref_tables")
            data = self._db.execute(f"SELECT data FROM {table} WHERE id = ?", (other,)).fetchone()
            existing = json.loads(data[0])["name"] if data else name
            what = {"enum": "list", "tree": "tree"}.get(kind, "table")
            raise RefValidationError(f"There is already a {what} called '{existing}'. Names must be unique "
                                     "across lists, trees and tables (ignoring case).", {"name": "Name already used"})
        self._db.execute("DELETE FROM ref_names WHERE object_id = ?", (object_id,))
        self._db.execute("INSERT INTO ref_names VALUES (?, ?, ?)", (key, kind, object_id))

    # lists
    def enums(self) -> dict[str, EnumList]:
        with self._lock:
            rows = self._db.execute("SELECT data FROM ref_enums").fetchall()
        return {e.id: e for e in (EnumList.model_validate_json(r[0]) for r in rows)}

    def get_enum(self, enum_id: str) -> EnumList:
        with self._lock:
            row = self._db.execute("SELECT data FROM ref_enums WHERE id = ?", (enum_id,)).fetchone()
        if not row:
            raise NotFound(enum_id)
        return EnumList.model_validate_json(row[0])

    def save_enum(self, enum: EnumList, create: bool = False) -> EnumList:
        enum = enum.model_copy(update={"updated_at": _now()})
        with self._lock, self._db:
            before = audit.data_of(self._db, "ref_enums", "id = ?", (enum.id,))
            if not create and before is None:
                raise NotFound(enum.id)
            self._claim_name("enum", enum.id, enum.name)
            self._db.execute("INSERT INTO ref_enums VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET data = excluded.data",
                             (enum.id, enum.model_dump_json()))
            audit.log(self._db, "ref_enum", enum.id, before, enum.model_dump_json())
        return enum

    def delete_enum(self, enum_id: str) -> None:
        with self._lock, self._db:
            before = audit.data_of(self._db, "ref_enums", "id = ?", (enum_id,))
            if before is not None:
                audit.log(self._db, "ref_enum", enum_id, before, None)
            self._db.execute("DELETE FROM ref_enums WHERE id = ?", (enum_id,))
            self._db.execute("DELETE FROM ref_names WHERE object_id = ?", (enum_id,))

    # trees
    def trees(self) -> list[RefTree]:
        with self._lock:
            rows = self._db.execute("SELECT data FROM ref_trees").fetchall()
        return [RefTree.model_validate_json(r[0]) for r in rows]

    def get_tree(self, tree_id: str) -> RefTree:
        with self._lock:
            row = self._db.execute("SELECT data FROM ref_trees WHERE id = ?", (tree_id,)).fetchone()
        if not row:
            raise NotFound(tree_id)
        return RefTree.model_validate_json(row[0])

    def save_tree(self, tree: RefTree, create: bool = False) -> RefTree:
        tree = tree.model_copy(update={"updated_at": _now()})
        with self._lock, self._db:
            before = audit.data_of(self._db, "ref_trees", "id = ?", (tree.id,))
            if not create and before is None:
                raise NotFound(tree.id)
            self._claim_name("tree", tree.id, tree.name)
            self._db.execute("INSERT INTO ref_trees VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET data = excluded.data",
                             (tree.id, tree.model_dump_json()))
            audit.log(self._db, "ref_tree", tree.id, before, tree.model_dump_json())
        return tree

    def delete_tree(self, tree_id: str) -> None:
        with self._lock, self._db:
            before = audit.data_of(self._db, "ref_trees", "id = ?", (tree_id,))
            if before is not None:
                audit.log(self._db, "ref_tree", tree_id, before, None)
            self._db.execute("DELETE FROM ref_trees WHERE id = ?", (tree_id,))
            self._db.execute("DELETE FROM ref_names WHERE object_id = ?", (tree_id,))

    # tables
    def tables(self) -> list[RefTable]:
        with self._lock:
            rows = self._db.execute("SELECT data FROM ref_tables").fetchall()
        return [RefTable.model_validate_json(r[0]) for r in rows]

    def row_counts(self) -> dict[str, int]:
        with self._lock:
            return dict(self._db.execute("SELECT table_id, COUNT(*) FROM ref_rows GROUP BY table_id").fetchall())

    def get_table(self, table_id: str) -> RefTable:
        with self._lock:
            row = self._db.execute("SELECT data FROM ref_tables WHERE id = ?", (table_id,)).fetchone()
        if not row:
            raise NotFound(table_id)
        return RefTable.model_validate_json(row[0])

    def save_table(self, table: RefTable, rows: list[RefRow] | None = None, create: bool = False) -> RefTable:
        """Save the table definition and, when given, the converted rows, in one transaction."""
        table = table.model_copy(update={"updated_at": _now()})
        with self._lock, self._db:
            before = audit.data_of(self._db, "ref_tables", "id = ?", (table.id,))
            if not create and before is None:
                raise NotFound(table.id)
            self._claim_name("table", table.id, table.name)
            # Upsert, not INSERT OR REPLACE: REPLACE deletes first, which would cascade to the rows.
            self._db.execute("INSERT INTO ref_tables VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET data = excluded.data",
                             (table.id, table.model_dump_json()))
            audit.log(self._db, "ref_table", table.id, before, table.model_dump_json())
            for r in rows or []:
                old = audit.data_of(self._db, "ref_rows", "id = ?", (r.id,))
                self._db.execute("UPDATE ref_rows SET data = ? WHERE id = ?", (r.model_dump_json(), r.id))
                if old is not None:
                    audit.log(self._db, "ref_row", r.id, old, r.model_dump_json(), parent_id=table.id,
                              label=f"{table.name}: row")
        return table

    def delete_table(self, table_id: str) -> None:
        with self._lock, self._db:
            before = audit.data_of(self._db, "ref_tables", "id = ?", (table_id,))
            if before is not None:
                (count,) = self._db.execute("SELECT COUNT(*) FROM ref_rows WHERE table_id = ?", (table_id,)).fetchone()
                audit.log(self._db, "ref_table", table_id, before, None,
                          note=f"{count} row(s) deleted with the table" if count else None)
            self._db.execute("DELETE FROM ref_tables WHERE id = ?", (table_id,))
            self._db.execute("DELETE FROM ref_names WHERE object_id = ?", (table_id,))

    # rows
    def rows(self, table_id: str) -> list[RefRow]:
        with self._lock:
            rows = self._db.execute("SELECT data FROM ref_rows WHERE table_id = ? ORDER BY seq", (table_id,)).fetchall()
        return [RefRow.model_validate_json(r[0]) for r in rows]

    def add_row(self, table_id: str, row: RefRow) -> RefRow:
        row = row.model_copy(update={"updated_at": _now()})
        with self._lock, self._db:
            (seq,) = self._db.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM ref_rows WHERE table_id = ?",
                                      (table_id,)).fetchone()
            self._db.execute("INSERT INTO ref_rows VALUES (?, ?, ?, ?)", (row.id, table_id, seq, row.model_dump_json()))
            audit.log(self._db, "ref_row", row.id, None, row.model_dump_json(), parent_id=table_id,
                      label=self._row_label(table_id))
        return row

    def update_row(self, table_id: str, row: RefRow) -> RefRow:
        row = row.model_copy(update={"updated_at": _now()})
        with self._lock, self._db:
            before = audit.data_of(self._db, "ref_rows", "id = ? AND table_id = ?", (row.id, table_id))
            if before is None:
                raise NotFound(row.id)
            self._db.execute("UPDATE ref_rows SET data = ? WHERE id = ? AND table_id = ?",
                             (row.model_dump_json(), row.id, table_id))
            audit.log(self._db, "ref_row", row.id, before, row.model_dump_json(), parent_id=table_id,
                      label=self._row_label(table_id), stored_time=json.loads(before).get("updated_at"))
        return row

    def _row_label(self, table_id: str) -> str:
        data = audit.data_of(self._db, "ref_tables", "id = ?", (table_id,))
        return f"{json.loads(data)['name']}: row" if data else "row"

    def delete_row(self, table_id: str, row_id: str) -> None:
        with self._lock, self._db:
            before = audit.data_of(self._db, "ref_rows", "id = ? AND table_id = ?", (row_id, table_id))
            if before is not None:
                audit.log(self._db, "ref_row", row_id, before, None, parent_id=table_id,
                          label=self._row_label(table_id), stored_time=json.loads(before).get("updated_at"))
            self._db.execute("DELETE FROM ref_rows WHERE id = ? AND table_id = ?", (row_id, table_id))


class KeyListStore:
    """The project's built-in lists. Shares the Store's connection and lock."""

    PLANT_AREAS = "plant-areas"
    EQUIPMENT_PACKAGES = "equipment-packages"
    LOAD_TYPES = "load-types"
    #: Code lists: id -> (model, change-log entity, label).
    CODE_LISTS = {"equipment-codes": (EquipmentCodeList, "equipment_codes", "Equipment Codes"),
                  "instrument-codes": (InstrumentCodeList, "instrument_codes", "Instrument Codes")}

    def __init__(self, store: Store):
        self._db = store._db
        self._lock = store._lock
        self._files = store.path.parent / "keylists" / self.LOAD_TYPES  # the PDFs attached to load types

    def plant_areas(self) -> PlantAreaList:
        with self._lock:
            row = self._db.execute("SELECT data FROM key_lists WHERE id = ?", (self.PLANT_AREAS,)).fetchone()
        return PlantAreaList.model_validate_json(row[0]) if row else PlantAreaList()

    def save_plant_areas(self, areas: PlantAreaList) -> PlantAreaList:
        areas = areas.model_copy(update={"updated_at": _now()})
        with self._lock, self._db:
            before = audit.data_of(self._db, "key_lists", "id = ?", (self.PLANT_AREAS,))
            self._db.execute("INSERT INTO key_lists VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET data = excluded.data",
                             (self.PLANT_AREAS, areas.model_dump_json()))
            # Every project has the list from the start (empty), so the first save is a change too.
            audit.log(self._db, "plant_areas", self.PLANT_AREAS, before or PlantAreaList().model_dump_json(),
                      areas.model_dump_json(), label="Plant Areas")
        return areas

    def equipment_packages(self) -> EquipmentPackageList:
        with self._lock:
            row = self._db.execute("SELECT data FROM key_lists WHERE id = ?", (self.EQUIPMENT_PACKAGES,)).fetchone()
        return EquipmentPackageList.model_validate_json(row[0]) if row else EquipmentPackageList()

    def save_equipment_packages(self, packages: EquipmentPackageList) -> EquipmentPackageList:
        packages = packages.model_copy(update={"updated_at": _now()})
        with self._lock, self._db:
            before = audit.data_of(self._db, "key_lists", "id = ?", (self.EQUIPMENT_PACKAGES,))
            self._db.execute("INSERT INTO key_lists VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET data = excluded.data",
                             (self.EQUIPMENT_PACKAGES, packages.model_dump_json()))
            audit.log(self._db, "equipment_packages", self.EQUIPMENT_PACKAGES,
                      before or EquipmentPackageList().model_dump_json(), packages.model_dump_json(),
                      label="Equipment Packages")
        return packages

    LOAD_SUMMARY = "load-summary"

    def load_summary(self):
        """The Load List Summary Page (keylists.load_summary); empty until first saved."""
        from workbench_core.keylists.load_summary import SummaryPage

        with self._lock:
            row = self._db.execute("SELECT data FROM key_lists WHERE id = ?", (self.LOAD_SUMMARY,)).fetchone()
        return SummaryPage.model_validate_json(row[0]) if row else SummaryPage()

    def save_load_summary(self, page):
        from workbench_core.keylists.load_summary import SummaryPage

        with self._lock, self._db:
            before = audit.data_of(self._db, "key_lists", "id = ?", (self.LOAD_SUMMARY,))
            self._db.execute("INSERT INTO key_lists VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET data = excluded.data",
                             (self.LOAD_SUMMARY, page.model_dump_json()))
            audit.log(self._db, "load_summary", self.LOAD_SUMMARY, before or SummaryPage().model_dump_json(), page.model_dump_json(),
                      label="Load List Summary Page")
        return page

    LOAD_FIELDS = "load-fields"

    def load_fields(self) -> LoadFields:
        """The project's Load List fields; the built-in ones until first saved."""
        with self._lock:
            row = self._db.execute("SELECT data FROM key_lists WHERE id = ?", (self.LOAD_FIELDS,)).fetchone()
        return LoadFields.model_validate_json(row[0]) if row else default_load_fields()

    def save_load_fields(self, change: FieldChange) -> LoadFields:
        """Save edited Load List fields and, in the same transaction, take deleted fields out of
        every import's mapping (their values then stop coming through)."""
        with self._lock, self._db:
            before = audit.data_of(self._db, "key_lists", "id = ?", (self.LOAD_FIELDS,))
            self._db.execute("INSERT INTO key_lists VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET data = excluded.data",
                             (self.LOAD_FIELDS, change.fields.model_dump_json()))
            audit.log(self._db, "load_fields", self.LOAD_FIELDS, before or default_load_fields().model_dump_json(),
                      change.fields.model_dump_json(), label="Load List fields")
            # Load List deliverables choose and filter columns by name: follow renamed and deleted fields
            from workbench_core.keylists.loadgen import load_list_columns

            old = LoadFields.model_validate_json(before) if before else default_load_fields()
            was = {src: name for name, src in load_list_columns(old)}
            now = {src: name for name, src in load_list_columns(change.fields)}
            cols = ColumnChange(columns=list(now.values()), renames={was[s_]: now[s_] for s_ in was if s_ in now and was[s_] != now[s_]},
                                deletes=[was[s_] for s_ in was if s_ not in now])
            if cols.renames or cols.deletes:
                for (data,) in self._db.execute("SELECT data FROM deliverables").fetchall():
                    d = Deliverable.model_validate_json(data)
                    if d.type != "Load List" or d.source != "project":
                        continue
                    f = rename_in([d.filter_column], cols) if d.filter_column else []
                    nd = d.model_copy(update={"columns": rename_in(d.columns, cols), "filter_column": f[0] if f else "",
                                              "filter_values": d.filter_values if f else []})
                    if nd != d:
                        self._db.execute("UPDATE deliverables SET data = ? WHERE id = ?", (nd.model_dump_json(), d.id))
                        audit.log(self._db, "deliverable", d.id, data, nd.model_dump_json(), note="Load List fields changed")
            if change.deletes:
                gone = set(change.deletes)
                for rid, data in self._db.execute("SELECT id, data FROM recipes").fetchall():
                    recipe = Recipe.model_validate_json(data)
                    if not is_load_target(recipe.target) or not any(m.field in gone for m in recipe.mapping):
                        continue
                    new = recipe.model_copy(update={"mapping": [m for m in recipe.mapping if m.field not in gone], "updated_at": _now()})
                    self._db.execute("UPDATE recipes SET data = ?, updated_at = ? WHERE id = ?",
                                     (new.model_dump_json(), new.updated_at.isoformat(), rid))
                    audit.log(self._db, "mel_recipe", rid, data, new.model_dump_json(), note="Load List fields deleted")
        return change.fields

    MASTER_COLUMNS = "master-columns"

    def master_columns(self) -> MasterColumns:
        """The project's columns of the master lists; the built-in ones until first saved."""
        with self._lock:
            row = self._db.execute("SELECT data FROM key_lists WHERE id = ?", (self.MASTER_COLUMNS,)).fetchone()
        return MasterColumns.model_validate_json(row[0]) if row else default_master_columns()

    def save_master_columns(self, changes: dict[str, ColumnChange]) -> MasterColumns:
        """Save edited master list columns and, in the same transaction, follow them in the
        load types' and equipment types' rows (renamed cells move, deleted ones are dropped)
        and in the column choices and filters of the deliverables made from those masters.
        Issued revisions are not touched."""
        with self._lock, self._db:
            row = self._db.execute("SELECT data FROM key_lists WHERE id = ?", (self.MASTER_COLUMNS,)).fetchone()
            before = row[0] if row else None
            cols = MasterColumns.model_validate_json(before) if before else default_master_columns()
            cols = MasterColumns(lists=cols.all() | {k: ch.columns for k, ch in changes.items()})
            self._db.execute("INSERT INTO key_lists VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET data = excluded.data",
                             (self.MASTER_COLUMNS, cols.model_dump_json()))
            audit.log(self._db, "master_columns", self.MASTER_COLUMNS, before or default_master_columns().model_dump_json(),
                      cols.model_dump_json(), label="Master list columns")
            if not any(ch.renames or ch.deletes for ch in changes.values()):
                return cols
            note = "Master list columns changed"
            lt_before = audit.data_of(self._db, "key_lists", "id = ?", (self.LOAD_TYPES,))
            if lt_before:
                loads = LoadTypeList.model_validate_json(lt_before)
                new = loads.model_copy(update={"items": [t.model_copy(update={"rows": rewrite_rows(t.rows, changes)[0]})
                                                         for t in loads.items]})
                if new != loads:
                    self._write_load_types(lt_before, new, note)
            ep_before = audit.data_of(self._db, "key_lists", "id = ?", (self.EQUIPMENT_PACKAGES,))
            if ep_before:
                packages = EquipmentPackageList.model_validate_json(ep_before)
                new_p = packages.model_copy(update={"types": [t.model_copy(update={"rows": rewrite_rows(t.rows, changes)[0]})
                                                              for t in packages.types]})
                if new_p != packages:
                    self._db.execute("UPDATE key_lists SET data = ? WHERE id = ?", (new_p.model_dump_json(), self.EQUIPMENT_PACKAGES))
                    audit.log(self._db, "equipment_packages", self.EQUIPMENT_PACKAGES, ep_before, new_p.model_dump_json(),
                              label="Equipment Packages", note=note)
            by_type = {LISTS[k].deliverable_type: ch for k, ch in changes.items()}
            for (data,) in self._db.execute("SELECT data FROM deliverables").fetchall():
                d = Deliverable.model_validate_json(data)
                ch = by_type.get(d.type)
                if d.source != "project" or ch is None:
                    continue
                f = rename_in([d.filter_column], ch) if d.filter_column else []
                nd = d.model_copy(update={"columns": rename_in(d.columns, ch), "filter_column": f[0] if f else "",
                                          "filter_values": d.filter_values if f else []})
                if nd != d:
                    self._db.execute("UPDATE deliverables SET data = ? WHERE id = ?", (nd.model_dump_json(), d.id))
                    audit.log(self._db, "deliverable", d.id, data, nd.model_dump_json(), note=note)
        return cols

    PLC = "plc"
    CABLE_TYPES = "cable-types"
    MOTORS = "motors"
    DRIVES = "drives"

    def drives(self):
        """Drive Data; a project that never saved it has the PowerFlex 755TS range (keylists.drives)."""
        from workbench_core.keylists.drives import DriveList, default_drives

        with self._lock:
            row = self._db.execute("SELECT data FROM key_lists WHERE id = ?", (self.DRIVES,)).fetchone()
        return DriveList.model_validate_json(row[0]) if row else DriveList(items=default_drives())

    INSTRUMENT_TYPES = "instrument-types"

    def instrument_types(self):
        """Instrument Types; a project that never saved it has the common ISA types (keylists.instrument_types)."""
        from workbench_core.keylists.instrument_types import InstrumentTypeList, default_instrument_types

        with self._lock:
            row = self._db.execute("SELECT data FROM key_lists WHERE id = ?", (self.INSTRUMENT_TYPES,)).fetchone()
        return InstrumentTypeList.model_validate_json(row[0]) if row else InstrumentTypeList(items=default_instrument_types())

    def save_instrument_types(self, items: list, note: str | None = None):
        from workbench_core.keylists.instrument_types import InstrumentTypeList, default_instrument_types

        it = InstrumentTypeList(items=items, updated_at=_now())
        with self._lock, self._db:
            before = audit.data_of(self._db, "key_lists", "id = ?", (self.INSTRUMENT_TYPES,))
            self._db.execute("INSERT INTO key_lists VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET data = excluded.data",
                             (self.INSTRUMENT_TYPES, it.model_dump_json()))
            audit.log(self._db, "instrument_types", self.INSTRUMENT_TYPES,
                      before or InstrumentTypeList(items=default_instrument_types()).model_dump_json(), it.model_dump_json(),
                      label="Instrument Types", note=note)
        return it

    PID_LOOPS = "pid-loops"

    def pid_loops(self):
        """What people decided about the PID Symbols' loops: instrument type and verified (keylists.pid_loops)."""
        from workbench_core.keylists.pid_loops import PidLoopStates

        with self._lock:
            row = self._db.execute("SELECT data FROM key_lists WHERE id = ?", (self.PID_LOOPS,)).fetchone()
        return PidLoopStates.model_validate_json(row[0]) if row else PidLoopStates()

    def save_pid_loop(self, loop: str, state, label: str = ""):
        """Save one loop's state (an empty one is removed); logged under the loop number."""
        from workbench_core.keylists.pid_loops import PidLoopState, PidLoopStates

        with self._lock, self._db:
            row = self._db.execute("SELECT data FROM key_lists WHERE id = ?", (self.PID_LOOPS,)).fetchone()
            states = PidLoopStates.model_validate_json(row[0]) if row else PidLoopStates()
            before = states.loops.get(loop, PidLoopState())
            if state == PidLoopState():
                states.loops.pop(loop, None)
            else:
                states.loops[loop] = state
            states.updated_at = _now()
            self._db.execute("INSERT INTO key_lists VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET data = excluded.data",
                             (self.PID_LOOPS, states.model_dump_json()))
            audit.log(self._db, "pid_loops", loop, before.model_dump_json(), state.model_dump_json(), label=label or f"Loop {loop}")
        return states

    LOAD_FACTORS = "load-factors"

    def load_factors(self):
        """Load Factors; a project that never saved it has the typical factors (keylists.load_factors)."""
        from workbench_core.keylists.load_factors import LoadFactorList, default_load_factors

        with self._lock:
            row = self._db.execute("SELECT data FROM key_lists WHERE id = ?", (self.LOAD_FACTORS,)).fetchone()
        return LoadFactorList.model_validate_json(row[0]) if row else LoadFactorList(items=default_load_factors())

    def save_load_factors(self, items: list, note: str | None = None):
        from workbench_core.keylists.load_factors import LoadFactorList, default_load_factors

        lf = LoadFactorList(items=items, updated_at=_now())
        with self._lock, self._db:
            before = audit.data_of(self._db, "key_lists", "id = ?", (self.LOAD_FACTORS,))
            self._db.execute("INSERT INTO key_lists VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET data = excluded.data",
                             (self.LOAD_FACTORS, lf.model_dump_json()))
            audit.log(self._db, "load_factors", self.LOAD_FACTORS, before or LoadFactorList(items=default_load_factors()).model_dump_json(),
                      lf.model_dump_json(), label="Load Factors", note=note)
        return lf

    STARTERS = "starters"

    def starters(self):
        """Starter Coordination; a project that never saved it has NHP's Type 2 charts, ECH64.2
        (65 kA) the default (keylists.starters)."""
        from workbench_core.keylists.starters import StarterList, default_starters

        with self._lock:
            row = self._db.execute("SELECT data FROM key_lists WHERE id = ?", (self.STARTERS,)).fetchone()
        return StarterList.model_validate_json(row[0]) if row else StarterList(items=default_starters())

    def save_starters(self, starters, note: str | None = None):
        """Save a StarterList (its rows and default chart)."""
        from workbench_core.keylists.starters import StarterList, default_starters

        starters = starters.model_copy(update={"updated_at": _now()})
        with self._lock, self._db:
            before = audit.data_of(self._db, "key_lists", "id = ?", (self.STARTERS,))
            self._db.execute("INSERT INTO key_lists VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET data = excluded.data",
                             (self.STARTERS, starters.model_dump_json()))
            audit.log(self._db, "starters", self.STARTERS, before or StarterList(items=default_starters()).model_dump_json(),
                      starters.model_dump_json(), label="Starter Coordination", note=note)
        return starters

    def save_drives(self, items: list, note: str | None = None):
        from workbench_core.keylists.drives import DriveList, default_drives

        drives = DriveList(items=items, updated_at=_now())
        with self._lock, self._db:
            before = audit.data_of(self._db, "key_lists", "id = ?", (self.DRIVES,))
            self._db.execute("INSERT INTO key_lists VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET data = excluded.data",
                             (self.DRIVES, drives.model_dump_json()))
            audit.log(self._db, "drives", self.DRIVES, before or DriveList(items=default_drives()).model_dump_json(),
                      drives.model_dump_json(), label="Drive Data", note=note)
        return drives

    def motors(self):
        """Motor Data; a project that never saved it has the WEG W22 range (keylists.motors)."""
        from workbench_core.keylists.motors import MotorList, default_motors

        with self._lock:
            row = self._db.execute("SELECT data FROM key_lists WHERE id = ?", (self.MOTORS,)).fetchone()
        return MotorList.model_validate_json(row[0]) if row else MotorList(items=default_motors())

    def save_motors(self, items: list, note: str | None = None):
        from workbench_core.keylists.motors import MotorList, default_motors

        motors = MotorList(items=items, updated_at=_now())
        with self._lock, self._db:
            before = audit.data_of(self._db, "key_lists", "id = ?", (self.MOTORS,))
            self._db.execute("INSERT INTO key_lists VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET data = excluded.data",
                             (self.MOTORS, motors.model_dump_json()))
            audit.log(self._db, "motors", self.MOTORS, before or MotorList(items=default_motors()).model_dump_json(),
                      motors.model_dump_json(), label="Motor Data", note=note)
        return motors

    def cable_types(self) -> CableTypeList:
        """The cable types; a project that never saved them has the default set."""
        with self._lock:
            row = self._db.execute("SELECT data FROM key_lists WHERE id = ?", (self.CABLE_TYPES,)).fetchone()
        if not row:
            return CableTypeList(items=default_cable_types())
        cables = CableTypeList.model_validate_json(row[0])
        if '"insulation"' not in row[0]:  # saved before the Insulation column: read it from the descriptions
            fill_insulation(cables.items)
        return cables

    def save_cable_types(self, items: list[CableType], note: str | None = None) -> CableTypeList:
        cables = CableTypeList(items=items, updated_at=_now())
        with self._lock, self._db:
            before = audit.data_of(self._db, "key_lists", "id = ?", (self.CABLE_TYPES,))
            self._db.execute("INSERT INTO key_lists VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET data = excluded.data",
                             (self.CABLE_TYPES, cables.model_dump_json()))
            # Before the first save the defaults are in effect, so that is what changed.
            audit.log(self._db, "cable_types", self.CABLE_TYPES,
                      before or CableTypeList(items=default_cable_types()).model_dump_json(), cables.model_dump_json(),
                      label="Cable Types", note=note)
        return cables

    # -- the catalogue of card and rack types (shared; kept where the generators kept it) --

    def catalogue(self) -> Catalogue:
        with self._lock:
            row = self._db.execute("SELECT data FROM settings WHERE key = 'gen_hw_catalogue'").fetchone()
        return Catalogue.model_validate_json(row[0]) if row else default_catalogue()

    def save_catalogue(self, cat: Catalogue) -> Catalogue:
        with self._lock, self._db:
            before = audit.data_of(self._db, "settings", "key = ?", ("gen_hw_catalogue",))
            self._db.execute("INSERT INTO settings VALUES ('gen_hw_catalogue', ?) "
                             "ON CONFLICT(key) DO UPDATE SET data = excluded.data", (cat.model_dump_json(),))
            # Before the first save the built-in defaults are in effect, so that is what changed.
            audit.log(self._db, "gen_catalogue", "catalogue", before or default_catalogue().model_dump_json(),
                      cat.model_dump_json(), label="Card and rack types")
        return cat

    # -- the PLC List ----------------------------------------------------------------------

    def plc(self) -> PlcList:
        """The PLC List. The first time, the generators' PLC hardware registers (as they were
        before the PLC List) are moved into it; their old records are left as they are."""
        with self._lock:
            row = self._db.execute("SELECT data FROM key_lists WHERE id = ?", (self.PLC,)).fetchone()
            if row:
                return PlcList.model_validate_json(row[0])
            registers = [Hardware.model_validate_json(d) for (d,) in self._db.execute("SELECT data FROM gen_hardware")]
        if not any(hw.panels for hw in registers):
            return PlcList()
        from workbench_core.refdata import name_key  # noqa: PLC0415
        areas = {name_key(n.tag): n.id for n in self.plant_areas().nodes}
        moved = from_registers(registers, areas, self.catalogue())
        return self.save_plc(moved, note="Moved from the generators' PLC hardware registers")

    def save_plc(self, plc: PlcList, note: str | None = None) -> PlcList:
        plc = plc.model_copy(update={"updated_at": _now()})
        with self._lock, self._db:
            before = audit.data_of(self._db, "key_lists", "id = ?", (self.PLC,))
            self._db.execute("INSERT INTO key_lists VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET data = excluded.data",
                             (self.PLC, plc.model_dump_json()))
            audit.log(self._db, "plc", "plc", before or PlcList().model_dump_json(), plc.model_dump_json(),
                      label="PLC List", note=note)
        return plc

    ENUMS = "enums"

    def enums(self) -> ProjectEnums:
        """The project's choice lists; a project that never saved them has the default set."""
        with self._lock:
            row = self._db.execute("SELECT data FROM key_lists WHERE id = ?", (self.ENUMS,)).fetchone()
        if not row:
            return default_enums()
        enums = ProjectEnums.model_validate_json(row[0])
        if '"document_types"' not in row[0]:  # saved before the Document List: it starts with the default document types
            enums.document_types = default_enums().document_types
        if '"x_proper"' not in row[0]:  # saved before xProper: it starts with the default words
            enums.x_proper = default_enums().x_proper
        return enums

    def disciplines(self) -> dict[str, str]:
        """The project's disciplines, code -> name, in their order."""
        return {d.code: d.name for d in self.enums().disciplines}

    def save_enums(self, enums: ProjectEnums) -> ProjectEnums:
        enums = enums.model_copy(update={"updated_at": _now()})
        with self._lock, self._db:
            before = audit.data_of(self._db, "key_lists", "id = ?", (self.ENUMS,))
            self._db.execute("INSERT INTO key_lists VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET data = excluded.data",
                             (self.ENUMS, enums.model_dump_json()))
            # Before the first save the defaults are in effect, so that is what changed.
            audit.log(self._db, "enums", self.ENUMS, before or default_enums().model_dump_json(), enums.model_dump_json(),
                      label="Enums")
        return enums

    DRAWING_LIST = "drawing-list"

    def drawing_list(self) -> DrawingList:
        with self._lock:
            row = self._db.execute("SELECT data FROM key_lists WHERE id = ?", (self.DRAWING_LIST,)).fetchone()
        return DrawingList.model_validate_json(row[0]) if row else DrawingList()

    def save_drawing_list(self, drawings: DrawingList, note: str | None = None) -> DrawingList:
        drawings = drawings.model_copy(update={"updated_at": _now()})
        with self._lock, self._db:
            before = audit.data_of(self._db, "key_lists", "id = ?", (self.DRAWING_LIST,))
            self._db.execute("INSERT INTO key_lists VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET data = excluded.data",
                             (self.DRAWING_LIST, drawings.model_dump_json()))
            audit.log(self._db, "drawing_list", self.DRAWING_LIST, before or DrawingList().model_dump_json(),
                      drawings.model_dump_json(), label="Drawing List", note=note)
        return drawings

    DOCUMENT_LIST = "document-list"

    def document_list(self) -> DocumentList:
        with self._lock:
            row = self._db.execute("SELECT data FROM key_lists WHERE id = ?", (self.DOCUMENT_LIST,)).fetchone()
        return DocumentList.model_validate_json(row[0]) if row else DocumentList()

    def save_document_list(self, documents: DocumentList, note: str | None = None) -> DocumentList:
        documents = documents.model_copy(update={"updated_at": _now()})
        with self._lock, self._db:
            before = audit.data_of(self._db, "key_lists", "id = ?", (self.DOCUMENT_LIST,))
            self._db.execute("INSERT INTO key_lists VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET data = excluded.data",
                             (self.DOCUMENT_LIST, documents.model_dump_json()))
            audit.log(self._db, "document_list", self.DOCUMENT_LIST, before or DocumentList().model_dump_json(),
                      documents.model_dump_json(), label="Document List", note=note)
        return documents

    INSTRUMENT_RUNSHEET = "instrument-runsheet"

    def instrument_runsheet(self) -> InstrumentRunsheet:
        with self._lock:
            row = self._db.execute("SELECT data FROM key_lists WHERE id = ?", (self.INSTRUMENT_RUNSHEET,)).fetchone()
        return InstrumentRunsheet.model_validate_json(row[0]) if row else InstrumentRunsheet()

    def save_instrument_runsheet(self, sheet: InstrumentRunsheet, note: str | None = None) -> InstrumentRunsheet:
        sheet = sheet.model_copy(update={"updated_at": _now()})
        with self._lock, self._db:
            before = audit.data_of(self._db, "key_lists", "id = ?", (self.INSTRUMENT_RUNSHEET,))
            self._db.execute("INSERT INTO key_lists VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET data = excluded.data",
                             (self.INSTRUMENT_RUNSHEET, sheet.model_dump_json()))
            # the record id is the one in the URL (/api/instrument-runsheet), for the version check
            audit.log(self._db, "instrument_runsheet", self.INSTRUMENT_RUNSHEET,
                      before or InstrumentRunsheet().model_dump_json(), sheet.model_dump_json(),
                      label="Instrument Runsheet", note=note)
        return sheet

    DISTRIBUTION_PANELS = "distribution-panels"

    def distribution_panels(self) -> DistributionPanelList:
        with self._lock:
            row = self._db.execute("SELECT data FROM key_lists WHERE id = ?", (self.DISTRIBUTION_PANELS,)).fetchone()
        return DistributionPanelList.model_validate_json(row[0]) if row else DistributionPanelList()

    def save_distribution_panels(self, panels: DistributionPanelList, note: str | None = None) -> DistributionPanelList:
        panels = panels.model_copy(update={"updated_at": _now()})
        with self._lock, self._db:
            before = audit.data_of(self._db, "key_lists", "id = ?", (self.DISTRIBUTION_PANELS,))
            self._db.execute("INSERT INTO key_lists VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET data = excluded.data",
                             (self.DISTRIBUTION_PANELS, panels.model_dump_json()))
            # the record id is the one in the URL (/api/distribution-panels), for the version check
            audit.log(self._db, "distribution_panels", self.DISTRIBUTION_PANELS,
                      before or DistributionPanelList().model_dump_json(), panels.model_dump_json(),
                      label="Distribution Panels", note=note)
        return panels

    EEL = "electrical-equipment"

    def eel(self) -> EelList:
        with self._lock:
            row = self._db.execute("SELECT data FROM key_lists WHERE id = ?", (self.EEL,)).fetchone()
        return EelList.model_validate_json(row[0]) if row else EelList()

    def save_eel(self, items: EelList) -> EelList:
        items = items.model_copy(update={"updated_at": _now()})
        with self._lock, self._db:
            before = audit.data_of(self._db, "key_lists", "id = ?", (self.EEL,))
            self._db.execute("INSERT INTO key_lists VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET data = excluded.data",
                             (self.EEL, items.model_dump_json()))
            # Logged as record "eel": the record the URL /api/eel names (for the stale-save check).
            audit.log(self._db, "eel", "eel", before or EelList().model_dump_json(), items.model_dump_json(),
                      label="Electrical Equipment List")
        return items

    def code_list(self, list_id: str):
        model = self.CODE_LISTS[list_id][0]
        with self._lock:
            row = self._db.execute("SELECT data FROM key_lists WHERE id = ?", (list_id,)).fetchone()
        return model.model_validate_json(row[0]) if row else model()

    def save_code_list(self, list_id: str, items: list):
        model, entity, label = self.CODE_LISTS[list_id]
        codes = model(items=items, updated_at=_now())
        with self._lock, self._db:
            before = audit.data_of(self._db, "key_lists", "id = ?", (list_id,))
            self._db.execute("INSERT INTO key_lists VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET data = excluded.data",
                             (list_id, codes.model_dump_json()))
            audit.log(self._db, entity, list_id, before or model().model_dump_json(), codes.model_dump_json(), label=label)
        return codes

    def load_types(self) -> LoadTypeList:
        with self._lock:
            row = self._db.execute("SELECT data FROM key_lists WHERE id = ?", (self.LOAD_TYPES,)).fetchone()
        return LoadTypeList.model_validate_json(row[0]) if row else LoadTypeList()

    def save_load_types(self, loads: LoadTypeList) -> LoadTypeList:
        """Save the rows. Attached PDFs are the engine's to record: each row keeps the PDF it
        has now (whatever the client sent), and the PDFs of deleted rows are deleted."""
        with self._lock, self._db:
            before = audit.data_of(self._db, "key_lists", "id = ?", (self.LOAD_TYPES,))
            old = LoadTypeList.model_validate_json(before) if before else LoadTypeList()
            pdfs = {r.id: r.pdf for r in old.items}
            loads = loads.model_copy(update={"updated_at": _now(), "items": [
                r.model_copy(update={"pdf": pdfs.get(r.id)}) for r in loads.items]})
            self._write_load_types(before, loads)
        kept = {r.id for r in loads.items}
        for r in old.items:
            if r.pdf and r.id not in kept:
                self.load_type_pdf(r.id).unlink(missing_ok=True)
        return loads

    def _write_load_types(self, before: str | None, loads: LoadTypeList, note: str | None = None) -> None:
        """Caller holds the lock and the transaction."""
        self._db.execute("INSERT INTO key_lists VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET data = excluded.data",
                         (self.LOAD_TYPES, loads.model_dump_json()))
        audit.log(self._db, "load_types", self.LOAD_TYPES, before or LoadTypeList().model_dump_json(),
                  loads.model_dump_json(), label="Load Types", note=note)

    def load_type_pdf(self, load_id: str) -> Path:
        """Where the PDF of a load type is kept (it may not exist)."""
        if not load_id.isalnum():
            raise NotFound(load_id)
        return self._files / f"{load_id}.pdf"

    def _set_load_type_pdf(self, load_id: str, pdf: AttachedFile | None, note: str) -> LoadTypeList:
        """Caller holds the lock and the transaction."""
        before = audit.data_of(self._db, "key_lists", "id = ?", (self.LOAD_TYPES,))
        loads = LoadTypeList.model_validate_json(before) if before else LoadTypeList()
        if not any(r.id == load_id for r in loads.items):
            raise NotFound(load_id)
        loads = loads.model_copy(update={"updated_at": _now(), "items": [
            r.model_copy(update={"pdf": pdf}) if r.id == load_id else r for r in loads.items]})
        self._write_load_types(before, loads, note=note)
        return loads

    def attach_load_type_pdf(self, load_id: str, data: bytes, file_name: str, pages: int) -> LoadTypeList:
        """Attach a PDF to a load type, replacing any it had."""
        path = self.load_type_pdf(load_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".pdf.part")
        tmp.write_bytes(data)
        try:
            with self._lock, self._db:
                pdf = AttachedFile(file_name=file_name, size=len(data), pages=pages, uploaded_at=_now())
                loads = self._set_load_type_pdf(load_id, pdf, f"PDF attached: {file_name} ({len(data):,} bytes)")
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)
        return loads

    def remove_load_type_pdf(self, load_id: str) -> LoadTypeList:
        path = self.load_type_pdf(load_id)
        with self._lock, self._db:
            loads = self._set_load_type_pdf(load_id, None, "PDF removed")
        path.unlink(missing_ok=True)
        return loads


class LoadListStore:
    """The Load List's remembered rows and their allocations. Shares the Store's connection and lock."""

    def __init__(self, store: Store):
        self._db = store._db
        self._lock = store._lock

    def _rows(self) -> dict[tuple[str, str], LoadListRow]:
        rows = (LoadListRow.model_validate_json(r[0]) for r in self._db.execute("SELECT data FROM load_list"))
        return {(r.recipe_id, r.key): r for r in rows}

    def rows(self) -> list[LoadListRow]:
        with self._lock:
            return list(self._rows().values())

    def _put(self, row: LoadListRow) -> None:
        self._db.execute("INSERT INTO load_list VALUES (?, ?, ?) ON CONFLICT(recipe_id, row_key) DO UPDATE SET "
                         "data = excluded.data", (row.recipe_id, row.key, row.model_dump_json(exclude={"factors"})))

    #: What a reset can clear, besides everything ("all").
    RESET_PARTS = ("plant_area", "load_type", "supply", "cable", "factors", "deleted")

    def reset(self, parts: set[str] | None = None) -> dict[str, int]:
        """Reset the Load List. With no `parts` (or "all"), every remembered row is forgotten,
        with its allocations and cable details and the rows kept as deleted. Otherwise only the
        named parts go: "plant_area" / "load_type": the ones a person chose; "supply": the
        distribution-panel ticks and supplied-from a person chose; "cable": every row's cable
        details; "deleted": the rows kept as deleted. The Electrical Equipment List's own
        allocations are never touched. The next sync fills in again what the imports give.
        Returns how many rows each part changed."""
        parts = set(parts or {"all"})
        counts: dict[str, int] = {}
        with self._lock, self._db:
            rows = self._rows()
            if "all" in parts:
                self._db.execute("DELETE FROM load_list")
                counts["all"] = len(rows)
            else:
                blank_cable = {"cable_length": None, "cable_construction": None, "cable_parallel": None, "cable_insulation": "",
                               "cable_size": "", "earth_size": ""}
                for key, row in rows.items():
                    if "deleted" in parts and row.status == "deleted":
                        self._db.execute("DELETE FROM load_list WHERE recipe_id = ? AND row_key = ?", key)
                        counts["deleted"] = counts.get("deleted", 0) + 1
                        continue
                    update: dict[str, object] = {}
                    for kind in ("plant_area", "load_type"):
                        if kind in parts and getattr(row, f"{kind}_by") == "user":
                            update |= {f"{kind}_id": None, f"{kind}_by": None}
                            counts[kind] = counts.get(kind, 0) + 1
                    if "supply" in parts and "user" in (row.is_panel_by, row.supplied_from_by):
                        if row.is_panel_by == "user":
                            update |= {"is_panel": False, "is_panel_by": None}
                        if row.supplied_from_by == "user":
                            update |= {"supplied_from": None, "supplied_from_by": None}
                        counts["supply"] = counts.get("supply", 0) + 1
                    if "cable" in parts and any(getattr(row, f) != v for f, v in blank_cable.items()):
                        update |= blank_cable
                        counts["cable"] = counts.get("cable", 0) + 1
                    if "factors" in parts and any(getattr(row, f) is not None for f in FACTOR_FIELDS):
                        update |= dict.fromkeys(FACTOR_FIELDS)
                        counts["factors"] = counts.get("factors", 0) + 1
                    if update:
                        self._put(row.model_copy(update=update))
            if counts:
                names = {"all": "rows forgotten", "plant_area": "plant areas cleared", "load_type": "load types cleared",
                         "supply": "panels and supplies cleared", "cable": "cable details cleared", "factors": "load factor overrides cleared",
                         "deleted": "deleted rows removed"}
                audit.log(self._db, "load_list", "load-list", None, {names[k]: n for k, n in counts.items()}, label="Load List",
                          note="Reset" + (": every row forgotten, then read again from the imports" if "all" in parts else ""))
        return counts

    #: What a person can set on a row, and the field that says who set it.
    EDITABLE = {"plant_area_id": "plant_area_by", "load_type_id": "load_type_by", "is_panel": "is_panel_by",
                "supplied_from": "supplied_from_by"}

    def sync(self, live: list[LoadListRow], gone: dict[str, str], areas: dict[str, str | None],
             types: dict) -> list[LoadListRow]:
        """Bring the remembered rows up to date with the imports and return them all.

        `live`: the rows the imports give now (status set: a row its file marks deleted is
        "deleted"). `gone`: import id -> why its remembered rows that aren't live are now
        deleted, for each import whose rows are known (every MEL/EEL import, and any
        remembered import that is no longer one). Imports not in `gone` keep their rows as
        they are. `areas` / `types`: the automatic-fill indexes (see keylists.loadlist)."""
        with self._lock, self._db:
            stored = self._rows()
            out: dict[tuple[str, str], LoadListRow] = {}
            for row in live:
                old = stored.get((row.recipe_id, row.key))
                base = old or LoadListRow(recipe_id=row.recipe_id, key=row.key, source=row.source, target=row.target)
                update = {"source": row.source, "target": row.target, "values": row.values, "status": row.status,
                          "deleted_reason": row.deleted_reason}
                if row.recipe_id == EEL_SOURCE:  # the Electrical Equipment List sets these itself
                    update |= {f: getattr(row, f) for f in self.EDITABLE} | {by: getattr(row, by) for by in self.EDITABLE.values()}
                out[(row.recipe_id, row.key)] = apply_auto(base.model_copy(update=update), areas, types)
            for k, old in stored.items():
                if k in out:
                    continue
                reason = gone.get(old.recipe_id)
                out[k] = old if reason is None else old.model_copy(update={"status": "deleted", "deleted_reason": reason})
            # Supplied from: once every row's panel flag is known. Automatic links that close a loop are dropped.
            panels = panel_index(list(out.values()))
            for row in live:
                k = (row.recipe_id, row.key)
                out[k] = apply_auto_supply(out[k], panels)
            by_ref = {r.ref(): r for r in out.values()}
            for ref in supply_loop(by_ref):
                r = by_ref[ref]
                if r.supplied_from_by == "auto":
                    out[(r.recipe_id, r.key)] = r.model_copy(update={"supplied_from": None, "supplied_from_by": None})
            filled = 0
            for k, row in out.items():
                old = stored.get(k) or LoadListRow(recipe_id=row.recipe_id, key=row.key, source=row.source, target=row.target)
                filled += sum(getattr(row, by) == "auto" and getattr(row, f) != getattr(old, f) for f, by in self.EDITABLE.items())
                if stored.get(k) != row:
                    self._put(row)
            if filled:
                audit.log(self._db, "load_list", "load-list", None, {"allocations filled in": filled}, label="Load List",
                          note="Filled in automatically from the imports")
        return list(out.values())

    def allocate(self, keys: list[tuple[str, str]], change: dict[str, object], labels: dict[str, str]) -> list[LoadListRow]:
        """Set the plant area, load type, distribution-panel flag and/or supplied-from of rows
        (`change`: keys of EDITABLE), as a person's choice. `labels`: plant area / load type id
        -> text for the change log. One row's edit is checked against the version the client
        last saw (see audit.check). Raises RefValidationError for a choice that breaks a rule."""
        out = []
        with self._lock, self._db:
            stored = self._rows()
            rows = []
            for k in keys:
                if k not in stored:
                    raise NotFound(f"{k[0]}/{k[1]}")
                if k[0] == EEL_SOURCE and any(f in self.EDITABLE for f in change):
                    raise RefValidationError(f"{stored[k].tag()} is from the Electrical Equipment List: change it there.",
                                             {"rows": "From the Electrical Equipment List"})
                rows.append(stored[k])
            by_ref = {r.ref(): r for r in stored.values()}

            def supply_label(ref: str | None) -> str | None:
                if ref is None or ref == PRIMARY_SUPPLY:
                    return "Primary Supply" if ref else None
                return by_ref[ref].tag() if ref in by_ref else ref

            def shown(r: LoadListRow) -> dict:
                return {"plant area": labels.get(r.plant_area_id or "", r.plant_area_id),
                        "load type": labels.get(r.load_type_id or "", r.load_type_id),
                        "distribution panel": "yes" if r.is_panel else "no", "supplied from": supply_label(r.supplied_from),
                        "cable length (m)": r.cable_length, "power cable": r.cable_construction,
                        "parallel cables": r.cable_parallel, "cable insulation": r.cable_insulation or None,
                        "cable size": r.cable_size or None, "earth size": r.earth_size or None,
                        "nameplate LF": r.lf_nameplate, "optimised LF": r.lf_optimised, "avg demand factor": r.lf_avg_demand,
                        "max demand factor": r.lf_max_demand}

            supply = change.get("supplied_from")
            if supply is not None and supply != PRIMARY_SUPPLY:
                panel = by_ref.get(str(supply))
                if panel is None:
                    raise RefValidationError("That distribution panel is no longer in the Load List. Open it again.",
                                             {"supplied_from": "Not found"})
                if not panel.is_panel or panel.status != "active":
                    raise RefValidationError(f"{panel.tag()} is not an active distribution panel.", {"supplied_from": "Not a panel"})
                if any(r.ref() == supply for r in rows):
                    raise RefValidationError(f"{panel.tag()} can't be supplied from itself.", {"supplied_from": "Itself"})
            if change.get("is_panel") is False:
                changed = {r.ref() for r in rows}
                fed = {}
                for r in stored.values():
                    if r.supplied_from in changed and r.supplied_from_by in KEPT and r.ref() not in changed:
                        fed[r.supplied_from] = fed.get(r.supplied_from, 0) + 1
                if fed:
                    raise RefValidationError(
                        "These distribution panels supply other rows: "
                        + ", ".join(f"{by_ref[ref].tag()} ({n} row{'s' if n > 1 else ''})" for ref, n in fed.items())
                        + ". Change what those rows are supplied from first.", {"is_panel": "Supplies rows"})

            new_rows: dict[str, LoadListRow] = {}
            for row in rows:
                update: dict[str, object] = {"updated_at": _now()}
                for field, value in change.items():
                    update[field] = value
                    if field in self.EDITABLE:
                        update[self.EDITABLE[field]] = "user"
                new_rows[row.ref()] = row.model_copy(update=update)
            graph = {**by_ref, **new_rows}
            if change.get("is_panel") is False:  # automatic links to a panel that isn't one any more go
                for ref, r in list(graph.items()):
                    if r.supplied_from in new_rows and r.supplied_from_by == "auto":
                        graph[ref] = r.model_copy(update={"supplied_from": None, "supplied_from_by": None})
                        self._put(graph[ref])
            loop = [ref for ref in supply_loop(graph) if ref in new_rows or graph[ref].supplied_from in new_rows]
            if loop:
                raise RefValidationError("That would make a supply loop: " + " → ".join(graph[r].tag() for r in loop)
                                         + ". A panel can't be supplied, directly or through other panels, from a row it supplies.",
                                         {"supplied_from": "Loop"})
            for row in rows:
                new = new_rows[row.ref()]
                self._put(new)
                audit.log(self._db, "load_list_row", row.ref(), shown(row), shown(new), parent_id=row.recipe_id,
                          label=row.tag(), stored_time=row.updated_at.isoformat() if row.updated_at and len(keys) == 1 else None)
                out.append(new)
        return out

    def used(self, kind: str) -> dict[str, int]:
        """Ids a person allocated (kind "plant_area" or "load_type") -> how many rows."""
        counts: dict[str, int] = {}
        for r in self.rows():
            if getattr(r, f"{kind}_by") in KEPT and getattr(r, f"{kind}_id"):
                counts[getattr(r, f"{kind}_id")] = counts.get(getattr(r, f"{kind}_id"), 0) + 1
        return counts


class DeliverableStore:
    """Deliverables and their issued revisions. Shares the Store's connection and lock."""

    def __init__(self, store: Store):
        self._db = store._db
        self._lock = store._lock

    def list(self) -> list[Deliverable]:
        with self._lock:
            rows = self._db.execute("SELECT data FROM deliverables").fetchall()
        return [Deliverable.model_validate_json(r[0]) for r in rows]

    def get(self, did: str) -> Deliverable:
        with self._lock:
            row = self._db.execute("SELECT data FROM deliverables WHERE id = ?", (did,)).fetchone()
        if not row:
            raise NotFound(did)
        return Deliverable.model_validate_json(row[0])

    def save(self, d: Deliverable, create: bool = False) -> Deliverable:
        d = d.model_copy(update={"updated_at": _now()})
        with self._lock, self._db:
            before = audit.data_of(self._db, "deliverables", "id = ?", (d.id,))
            if not create and before is None:
                raise NotFound(d.id)
            self._db.execute("INSERT INTO deliverables VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET data = excluded.data",
                             (d.id, d.model_dump_json()))
            audit.log(self._db, "deliverable", d.id, before, d.model_dump_json())
        return d

    def delete(self, did: str) -> None:
        """Only a deliverable with no revisions (the caller says so to the user first)."""
        with self._lock, self._db:
            (n,) = self._db.execute("SELECT COUNT(*) FROM deliverable_revisions WHERE deliverable_id = ?", (did,)).fetchone()
            if n:
                raise InUse(f"It has {n} issued revision(s).")
            before = audit.data_of(self._db, "deliverables", "id = ?", (did,))
            if before is not None:
                audit.log(self._db, "deliverable", did, before, None)
            self._db.execute("DELETE FROM deliverables WHERE id = ?", (did,))

    def revisions(self, did: str | None = None) -> list[IssueInfo]:
        """Newest first (all deliverables' when `did` is None)."""
        sql, args = "SELECT info FROM deliverable_revisions", ()
        if did is not None:
            sql, args = sql + " WHERE deliverable_id = ?", (did,)
        with self._lock:
            rows = self._db.execute(sql, args).fetchall()
        return sorted((IssueInfo.model_validate_json(r[0]) for r in rows), key=lambda r: r.issued_at, reverse=True)

    def revision(self, rid: str) -> IssuedRevision:
        with self._lock:
            row = self._db.execute("SELECT data FROM deliverable_revisions WHERE id = ?", (rid,)).fetchone()
        if not row:
            raise NotFound(rid)
        return IssuedRevision.model_validate_json(row[0])

    def latest(self, did: str) -> IssuedRevision | None:
        revs = self.revisions(did)
        return self.revision(revs[0].id) if revs else None

    def issue(self, d: Deliverable, make) -> IssuedRevision:
        """Issue the next revision. `make(letter, previous)` builds it once the letter is taken,
        inside the transaction, so two people issuing at once can't get the same letter."""
        with self._lock, self._db:
            rows = self._db.execute("SELECT info FROM deliverable_revisions WHERE deliverable_id = ?", (d.id,)).fetchall()
            infos = sorted((IssueInfo.model_validate_json(r[0]) for r in rows), key=lambda r: r.issued_at)
            previous = None
            if infos:
                (data,) = self._db.execute("SELECT data FROM deliverable_revisions WHERE id = ?", (infos[-1].id,)).fetchone()
                previous = IssuedRevision.model_validate_json(data)
            rev = make(next_letter([i.letter for i in infos]), previous)
            self._db.execute("INSERT INTO deliverable_revisions VALUES (?, ?, ?, ?, ?)",
                             (rev.info.id, d.id, rev.info.letter, rev.info.model_dump_json(), rev.model_dump_json()))
            audit.log(self._db, "deliverable_revision", rev.info.id, None, rev.info.model_dump_json(), parent_id=d.id,
                      label=f"{d.name}: Rev {rev.info.letter}", note=f"Rev {rev.info.letter} issued")
        return rev

    def set_description(self, rid: str, description: str) -> IssueInfo:
        with self._lock, self._db:
            row = self._db.execute("SELECT deliverable_id, info, data FROM deliverable_revisions WHERE id = ?", (rid,)).fetchone()
            if not row:
                raise NotFound(rid)
            did, old, data = row
            rev = IssuedRevision.model_validate_json(data)
            info = rev.info.model_copy(update={"description": description.strip()})
            rev = rev.model_copy(update={"info": info})
            self._db.execute("UPDATE deliverable_revisions SET info = ?, data = ? WHERE id = ?",
                             (info.model_dump_json(), rev.model_dump_json(), rid))
            audit.log(self._db, "deliverable_revision", rid, old, info.model_dump_json(), parent_id=did,
                      label=f"Rev {info.letter}")
        return info

    def withdraw(self, rid: str, reason: str) -> IssueInfo:
        """Withdraw a revision: only the latest of its deliverable. Its letter is free again."""
        with self._lock, self._db:
            row = self._db.execute("SELECT deliverable_id, info FROM deliverable_revisions WHERE id = ?", (rid,)).fetchone()
            if not row:
                raise NotFound(rid)
            did, old = row
            info = IssueInfo.model_validate_json(old)
            others = [IssueInfo.model_validate_json(r[0]) for r in self._db.execute(
                "SELECT info FROM deliverable_revisions WHERE deliverable_id = ?", (did,))]
            newest = max(others, key=lambda r: r.issued_at)
            if newest.id != rid:
                raise InUse(f"Only the latest revision (Rev {newest.letter}) can be withdrawn.")
            name = json.loads(audit.data_of(self._db, "deliverables", "id = ?", (did,)) or "{}").get("name", "")
            self._db.execute("DELETE FROM deliverable_revisions WHERE id = ?", (rid,))
            audit.log(self._db, "deliverable_revision", rid, old, None, parent_id=did,
                      label=f"{name}: Rev {info.letter}", note=f"Rev {info.letter} withdrawn: {reason.strip()}")
        return info

    def using(self, generator_id: str) -> list[str]:
        return [d.name for d in self.list() if d.generator_id == generator_id]

    def using_panel(self, panel_id: str) -> list[str]:
        """Names of the deliverables that issue this distribution panel's schedule."""
        return [d.name for d in self.list() if getattr(d, "panel_id", "") == panel_id]


class InUse(ValueError):
    pass


class SymbolStore:
    """Symbol libraries, templates, drawings, overrides, page results and runs. Shares the
    Store's connection and lock; big files (PDF, page PNGs, words) live next to the database."""

    def __init__(self, store: Store):
        self._db = store._db
        self._lock = store._lock
        self.root = store.path.parent / "symbols"

    # -- files ---------------------------------------------------------------

    def doc_dir(self, doc_id: str) -> Path:
        if not doc_id.isalnum():
            raise NotFound(doc_id)
        return self.root / doc_id

    def page_png(self, doc_id: str, n: int) -> Path:
        return self.doc_dir(doc_id) / f"page-{n}.png"

    def words_file(self, doc_id: str, n: int, kind: str = "pdf") -> Path:
        return self.doc_dir(doc_id) / f"page-{n}.{kind}.json"

    # -- libraries -------------------------------------------------------------

    def libraries(self) -> list[Library]:
        with self._lock:
            rows = self._db.execute("SELECT data FROM sym_libraries ORDER BY created_at").fetchall()
        return [Library.model_validate_json(r[0]) for r in rows]

    def get_library(self, library_id: str) -> Library:
        with self._lock:
            row = self._db.execute("SELECT data FROM sym_libraries WHERE id = ?", (library_id,)).fetchone()
        if not row:
            raise NotFound(library_id)
        return Library.model_validate_json(row[0])

    def unique_name(self, name: str) -> str:
        taken = {name_key(lib.name) for lib in self.libraries()}
        out, n = name.strip() or "Library", 2
        base = out
        while name_key(out) in taken:
            out, n = f"{base} ({n})", n + 1
        return out

    def save_library(self, lib: Library, create: bool = False) -> Library:
        try:
            with self._lock, self._db:
                if create:
                    self._db.execute("INSERT INTO sym_libraries VALUES (?, ?, ?, ?)",
                                     (lib.id, name_key(lib.name), lib.model_dump_json(), _now().isoformat()))
                    audit.log(self._db, "sym_library", lib.id, None, lib.model_dump_json())
                else:
                    before = audit.data_of(self._db, "sym_libraries", "id = ?", (lib.id,))
                    if before is None:
                        raise NotFound(lib.id)
                    self._db.execute("UPDATE sym_libraries SET name_key = ?, data = ? WHERE id = ?",
                                     (name_key(lib.name), lib.model_dump_json(), lib.id))
                    audit.log(self._db, "sym_library", lib.id, before, lib.model_dump_json())
        except sqlite3.IntegrityError as exc:
            raise RefValidationError(f"There is already a library called '{lib.name}'.", {"name": "Already used."}) from exc
        return lib

    def delete_library(self, library_id: str) -> None:
        with self._lock:
            (n,) = self._db.execute("SELECT COUNT(*) FROM sym_drawings WHERE library_id = ?", (library_id,)).fetchone()
        if n:
            raise InUse(f"{n} drawing(s) use this library. Move them to another library or remove them first.")
        with self._lock, self._db:
            before = audit.data_of(self._db, "sym_libraries", "id = ?", (library_id,))
            if before is not None:
                (count,) = self._db.execute("SELECT COUNT(*) FROM sym_templates WHERE library_id = ?",
                                            (library_id,)).fetchone()
                audit.log(self._db, "sym_library", library_id, before, None,
                          note=f"{count} template(s) deleted with the library" if count else None)
            self._db.execute("DELETE FROM sym_libraries WHERE id = ?", (library_id,))

    # -- drawings --------------------------------------------------------------

    def add_drawing(self, drawing: Drawing, pdf: bytes) -> Drawing:
        d = self.doc_dir(drawing.id)
        d.mkdir(parents=True, exist_ok=True)
        (d / "source.pdf").write_bytes(pdf)
        with self._lock, self._db:
            self._db.execute("INSERT INTO sym_drawings VALUES (?, ?, ?, ?)",
                             (drawing.id, drawing.library_id, drawing.model_dump_json(), _now().isoformat()))
            audit.log(self._db, "sym_drawing", drawing.id, None, self._drawing_summary(drawing.model_dump_json()),
                      note=f"PDF uploaded ({len(pdf):,} bytes)")
        return drawing

    @staticmethod
    def _drawing_summary(data: str) -> dict:
        """A drawing without its per-page render details, which the engine fills in, not the user."""
        d = json.loads(data)
        pages = d.pop("pages", None)
        if isinstance(pages, list):
            d["page_count"] = len(pages)
        return d

    def save_drawing(self, drawing: Drawing) -> Drawing:
        with self._lock, self._db:
            before = audit.data_of(self._db, "sym_drawings", "id = ?", (drawing.id,))
            if before is None:
                raise NotFound(drawing.id)
            self._db.execute("UPDATE sym_drawings SET library_id = ?, data = ? WHERE id = ?",
                             (drawing.library_id, drawing.model_dump_json(), drawing.id))
            audit.log(self._db, "sym_drawing", drawing.id, self._drawing_summary(before),
                      self._drawing_summary(drawing.model_dump_json()))
        return drawing

    def drawings(self) -> list[Drawing]:
        with self._lock:
            rows = self._db.execute("SELECT data FROM sym_drawings ORDER BY created_at").fetchall()
        return [Drawing.model_validate_json(r[0]) for r in rows]

    def get_drawing(self, doc_id: str) -> Drawing:
        with self._lock:
            row = self._db.execute("SELECT data FROM sym_drawings WHERE id = ?", (doc_id,)).fetchone()
        if not row:
            raise NotFound(doc_id)
        return Drawing.model_validate_json(row[0])

    def delete_drawing(self, doc_id: str) -> None:
        import shutil
        with self._lock, self._db:
            before = audit.data_of(self._db, "sym_drawings", "id = ?", (doc_id,))
            if before is not None:
                audit.log(self._db, "sym_drawing", doc_id, self._drawing_summary(before), None)
            self._db.execute("DELETE FROM sym_drawings WHERE id = ?", (doc_id,))
        shutil.rmtree(self.doc_dir(doc_id), ignore_errors=True)

    # -- templates -------------------------------------------------------------

    def templates(self, library_id: str | None = None) -> list[Template]:
        sql, args = "SELECT data FROM sym_templates", []
        if library_id is not None:
            sql, args = sql + " WHERE library_id = ?", [library_id]
        with self._lock:
            rows = self._db.execute(sql + " ORDER BY library_id, priority", args).fetchall()
        return [Template.model_validate_json(r[0]) for r in rows]

    def get_template(self, template_id: str) -> Template:
        with self._lock:
            row = self._db.execute("SELECT data FROM sym_templates WHERE id = ?", (template_id,)).fetchone()
        if not row:
            raise NotFound(template_id)
        return Template.model_validate_json(row[0])

    def template_image(self, template_id: str) -> bytes:
        with self._lock:
            row = self._db.execute("SELECT image FROM sym_templates WHERE id = ?", (template_id,)).fetchone()
        if not row:
            raise NotFound(template_id)
        return bytes(row[0])

    def template_mask(self, template_id: str) -> bytes | None:
        """The user's custom mask (PNG, white = scored), if any."""
        with self._lock:
            row = self._db.execute("SELECT mask FROM sym_templates WHERE id = ?", (template_id,)).fetchone()
        if not row:
            raise NotFound(template_id)
        return bytes(row[0]) if row[0] is not None else None

    def template_view(self, template_id: str) -> tuple[bytes, list[Word]] | None:
        """The template as it was on the page, with its text, and the text's boxes in template
        pixels; None for a template that has no view (uploaded, or cut before views were kept)."""
        self.get_template(template_id)
        with self._lock:
            row = self._db.execute("SELECT image, words FROM sym_template_views WHERE template_id = ?",
                                   (template_id,)).fetchone()
        if not row:
            return None
        return bytes(row[0]), [Word.model_validate(w) for w in json.loads(row[1])]

    def set_template_view(self, template_id: str, png: bytes, words: list[Word]) -> None:
        with self._lock, self._db:
            self._db.execute("INSERT OR REPLACE INTO sym_template_views VALUES (?, ?, ?)",
                             (template_id, png, json.dumps([w.model_dump(mode="json") for w in words])))

    def add_template(self, t: Template, png: bytes, mask: bytes | None = None, log: bool = True) -> Template:
        """Append to the end of its library's priority list."""
        self.get_library(t.library_id)
        with self._lock, self._db:
            (count,) = self._db.execute("SELECT COUNT(*) FROM sym_templates WHERE library_id = ?",
                                        (t.library_id,)).fetchone()
            t = t.model_copy(update={"priority": count, "has_custom_mask": mask is not None})
            self._db.execute("INSERT INTO sym_templates VALUES (?, ?, ?, ?, ?, ?)",
                             (t.id, t.library_id, t.priority, t.model_dump_json(), png, mask))
            if log:
                audit.log(self._db, "sym_template", t.id, None, t.model_dump_json(), parent_id=t.library_id,
                          note=f"image {len(png):,} bytes")
        return t

    def save_template(self, t: Template) -> Template:
        """Edit fields. Moving library re-appends it there; priority changes go through move."""
        old = self.get_template(t.id)
        if old.library_id != t.library_id:
            png, mask, view = self.template_image(t.id), self.template_mask(t.id), self.template_view(t.id)
            with self._lock, self._db:
                audit.check(self._db, "sym_template", t.id)
                self._db.execute("DELETE FROM sym_templates WHERE id = ?", (t.id,))
                self._renumber(old.library_id)
            new = self.add_template(t.model_copy(update={"width": old.width, "height": old.height}), png, mask, log=False)
            if view:
                self.set_template_view(t.id, *view)
            with self._lock, self._db:
                audit.log(self._db, "sym_template", t.id, old.model_dump_json(), new.model_dump_json(),
                          parent_id=new.library_id)
            return new
        t = t.model_copy(update={"priority": old.priority, "width": old.width, "height": old.height,
                                 "has_custom_mask": old.has_custom_mask})
        with self._lock, self._db:
            self._db.execute("UPDATE sym_templates SET data = ? WHERE id = ?", (t.model_dump_json(), t.id))
            audit.log(self._db, "sym_template", t.id, old.model_dump_json(), t.model_dump_json(), parent_id=t.library_id)
        return t

    def set_template_mask(self, template_id: str, mask: bytes | None) -> Template:
        old = self.get_template(template_id)
        t = old.model_copy(update={"has_custom_mask": mask is not None})
        if mask is None and t.mask_mode == "custom":
            t.mask_mode = "auto"
        elif mask is not None:
            t.mask_mode = "custom"
        with self._lock, self._db:
            self._db.execute("UPDATE sym_templates SET mask = ?, data = ? WHERE id = ?", (mask, t.model_dump_json(), t.id))
            audit.log(self._db, "sym_template", t.id, old.model_dump_json(), t.model_dump_json(), parent_id=t.library_id,
                      note="custom mask removed" if mask is None else f"custom mask drawn ({len(mask):,} bytes)")
        return t

    def _renumber(self, library_id: str, order: list[str] | None = None) -> None:
        """Rewrite priorities 0..n-1 (caller holds the lock and transaction). Two passes keep
        the (library, priority) unique constraint satisfied throughout."""
        ids = order or [r[0] for r in self._db.execute(
            "SELECT id FROM sym_templates WHERE library_id = ? ORDER BY priority", (library_id,))]
        for i, tid in enumerate(ids):
            self._db.execute("UPDATE sym_templates SET priority = ? WHERE id = ?", (-1 - i, tid))
        for i, tid in enumerate(ids):
            (data,) = self._db.execute("SELECT data FROM sym_templates WHERE id = ?", (tid,)).fetchone()
            t = Template.model_validate_json(data).model_copy(update={"priority": i})
            self._db.execute("UPDATE sym_templates SET priority = ?, data = ? WHERE id = ?", (i, t.model_dump_json(), tid))

    def move_template(self, template_id: str, index: int) -> Template:
        t = self.get_template(template_id)
        with self._lock, self._db:
            ids = [r[0] for r in self._db.execute(
                "SELECT id FROM sym_templates WHERE library_id = ? ORDER BY priority", (t.library_id,))]
            ids.remove(template_id)
            ids.insert(max(0, min(index, len(ids))), template_id)
            self._renumber(t.library_id, ids)
            after = audit.data_of(self._db, "sym_templates", "id = ?", (template_id,))
            audit.log(self._db, "sym_template", template_id, t.model_dump_json(), after, parent_id=t.library_id)
        return self.get_template(template_id)

    def delete_template(self, template_id: str) -> None:
        t = self.get_template(template_id)
        with self._lock, self._db:
            audit.log(self._db, "sym_template", template_id, t.model_dump_json(), None, parent_id=t.library_id)
            self._db.execute("DELETE FROM sym_templates WHERE id = ?", (template_id,))
            self._renumber(t.library_id)

    # -- overrides and results ---------------------------------------------------

    def overrides(self, doc_id: str, page: int) -> dict[str, PageOverride]:
        with self._lock:
            rows = self._db.execute("SELECT data FROM sym_overrides WHERE doc_id = ? AND page = ?", (doc_id, page)).fetchall()
        return {o.template_id: o for o in (PageOverride.model_validate_json(r[0]) for r in rows)}

    def set_override(self, doc_id: str, page: int, ov: PageOverride) -> PageOverride:
        self.get_drawing(doc_id)
        self.get_template(ov.template_id)
        with self._lock, self._db:
            where, args = "doc_id = ? AND page = ? AND template_id = ?", (doc_id, page, ov.template_id)
            before = audit.data_of(self._db, "sym_overrides", where, args)
            self._db.execute("INSERT INTO sym_overrides VALUES (?, ?, ?, ?) ON CONFLICT(doc_id, page, template_id) "
                             "DO UPDATE SET data = excluded.data", (doc_id, page, ov.template_id, ov.model_dump_json()))
            audit.log(self._db, "sym_override", f"{doc_id}/{page}/{ov.template_id}", before, ov.model_dump_json(),
                      parent_id=doc_id, label=f"Page {page} override")
        return ov

    def delete_override(self, doc_id: str, page: int, template_id: str) -> None:
        with self._lock, self._db:
            where, args = "doc_id = ? AND page = ? AND template_id = ?", (doc_id, page, template_id)
            before = audit.data_of(self._db, "sym_overrides", where, args)
            if before is not None:
                audit.log(self._db, "sym_override", f"{doc_id}/{page}/{template_id}", before, None,
                          parent_id=doc_id, label=f"Page {page} override")
            self._db.execute(f"DELETE FROM sym_overrides WHERE {where}", args)

    def save_result(self, doc_id: str, result: PageResult) -> None:
        with self._lock, self._db:
            self._db.execute("INSERT INTO sym_results VALUES (?, ?, ?) ON CONFLICT(doc_id, page) "
                             "DO UPDATE SET data = excluded.data", (doc_id, result.page, result.model_dump_json()))

    def result(self, doc_id: str, page: int) -> PageResult | None:
        with self._lock:
            row = self._db.execute("SELECT data FROM sym_results WHERE doc_id = ? AND page = ?", (doc_id, page)).fetchone()
        return PageResult.model_validate_json(row[0]) if row else None

    def review(self, doc_id: str, page: int) -> PageReview:
        """The user's corrections to a page (false positives, symbols added by hand)."""
        with self._lock:
            row = self._db.execute("SELECT data FROM sym_reviews WHERE doc_id = ? AND page = ?", (doc_id, page)).fetchone()
        return PageReview.model_validate_json(row[0]) if row else PageReview()

    def save_review(self, doc_id: str, page: int, review: PageReview) -> PageReview:
        self.get_drawing(doc_id)
        with self._lock, self._db:
            before = audit.data_of(self._db, "sym_reviews", "doc_id = ? AND page = ?", (doc_id, page))
            self._db.execute("INSERT INTO sym_reviews VALUES (?, ?, ?) ON CONFLICT(doc_id, page) "
                             "DO UPDATE SET data = excluded.data", (doc_id, page, review.model_dump_json()))
            audit.log(self._db, "sym_review", f"{doc_id}/{page}", before, review.model_dump_json(),
                      parent_id=doc_id, label=f"Page {page} review")
        return review

    # -- runs ------------------------------------------------------------------

    def save_run(self, run: RunInfo, sheets: list[dict] | None = None) -> RunInfo:
        with self._lock, self._db:
            if not self._db.execute("SELECT 1 FROM sym_runs WHERE id = ?", (run.id,)).fetchone():
                audit.log(self._db, "sym_run", run.id, None, run.model_dump_json(), label="Detection run")
            self._db.execute("INSERT INTO sym_runs (id, info, created_at) VALUES (?, ?, ?) ON CONFLICT(id) "
                             "DO UPDATE SET info = excluded.info", (run.id, run.model_dump_json(), _now().isoformat()))
            if sheets is not None:
                self._db.execute("UPDATE sym_runs SET sheets = ? WHERE id = ?", (json.dumps(sheets), run.id))
        return run

    def runs(self) -> list[RunInfo]:
        with self._lock:
            rows = self._db.execute("SELECT info FROM sym_runs ORDER BY created_at DESC").fetchall()
        return [RunInfo.model_validate_json(r[0]) for r in rows]

    def get_run(self, run_id: str) -> tuple[RunInfo, list[dict]]:
        with self._lock:
            row = self._db.execute("SELECT info, sheets FROM sym_runs WHERE id = ?", (run_id,)).fetchone()
        if not row:
            raise NotFound(run_id)
        return RunInfo.model_validate_json(row[0]), json.loads(row[1])

    def update_run_sheet(self, run: RunInfo, index: int, sheet: dict) -> None:
        """Replace one sheet of a finished run (after a review correction) and its info."""
        with self._lock, self._db:
            row = self._db.execute("SELECT sheets FROM sym_runs WHERE id = ?", (run.id,)).fetchone()
            if not row:
                raise NotFound(run.id)
            sheets = json.loads(row[0])
            sheets[index] = sheet
            self._db.execute("UPDATE sym_runs SET info = ?, sheets = ? WHERE id = ?",
                             (run.model_dump_json(), json.dumps(sheets), run.id))

    def delete_run(self, run_id: str) -> None:
        with self._lock, self._db:
            before = audit.data_of(self._db, "sym_runs", "id = ?", (run_id,), "info")
            if before is not None:
                audit.log(self._db, "sym_run", run_id, before, None, label="Detection run")
            self._db.execute("DELETE FROM sym_runs WHERE id = ?", (run_id,))

    # -- first run -------------------------------------------------------------

    def seeded(self) -> bool:
        with self._lock:
            return self._db.execute("SELECT 1 FROM settings WHERE key = 'symbols_seeded'").fetchone() is not None

    def mark_seeded(self) -> None:
        with self._lock, self._db:
            self._db.execute("INSERT INTO settings VALUES ('symbols_seeded', '1') ON CONFLICT(key) DO NOTHING")


class GeneratorStore:
    """Generators and their builds. Shares the Store's connection and lock."""

    def __init__(self, store: Store):
        self._db, self._lock = store._db, store._lock

    def create(self, name: str, kind: str, source_file: str, gen: Generator, tables: dict[str, GenTable],
               report: ImportReport | None = None) -> GenRecord:
        rid = uuid.uuid4().hex
        now = _now()
        gen = gen.model_copy(update={"tables": {}})
        with self._lock, self._db:
            self._db.execute("INSERT INTO gen_generators VALUES (?, ?, ?, ?, ?, ?, ?)",
                             (rid, name, kind, source_file, now.isoformat(), gen.model_dump_json(),
                              report.model_dump_json() if report else None))
            self._db.executemany("INSERT INTO gen_tables VALUES (?, ?, ?)",
                                 [(rid, n, t.model_dump_json()) for n, t in tables.items()])
            audit.log(self._db, "generator", rid, None,
                      {"name": name, "kind": kind, "source_file": source_file, "runs": len(gen.runsheet.rows),
                       "templates": len({t.id for t in gen.templates}), "tables": sorted(tables)})
        return self.get(rid)

    def list(self) -> list[GenSummary]:
        with self._lock:
            rows = self._db.execute("SELECT id, name, kind, source_file, updated_at, data FROM gen_generators "
                                    "ORDER BY updated_at DESC").fetchall()
            latest = {gid: info for gid, info in self._db.execute(
                "SELECT b.generator_id, b.info FROM gen_builds b JOIN (SELECT generator_id, MAX(seq) m FROM gen_builds "
                "GROUP BY generator_id) x ON x.generator_id = b.generator_id AND x.m = b.seq").fetchall()}
        out = []
        for i, n, k, src, u, data in rows:
            g = Generator.model_validate_json(data)
            out.append(GenSummary(id=i, name=n, kind=k, source_file=src, updated_at=u, runs=len(g.runsheet.rows),
                                  templates=len({t.id for t in g.templates}),
                                  last_build=BuildInfo.model_validate_json(latest[i]) if i in latest else None))
        return out

    def get(self, rid: str) -> GenRecord:
        with self._lock:
            row = self._db.execute("SELECT name, kind, source_file, updated_at, data, report FROM gen_generators "
                                   "WHERE id = ?", (rid,)).fetchone()
            trows = self._db.execute("SELECT name, data FROM gen_tables WHERE generator_id = ?", (rid,)).fetchall()
        if not row:
            raise NotFound(rid)
        name, kind, src, upd, data, report = row
        tables = {n: GenTable.model_validate_json(d) for n, d in trows}
        return GenRecord(id=rid, name=name, kind=kind, source_file=src, updated_at=upd,
                         generator=Generator.model_validate_json(data), tables=summarise(tables),
                         import_report=ImportReport.model_validate_json(report) if report else None)

    def tables(self, rid: str) -> dict[str, GenTable]:
        self.get(rid)
        with self._lock:
            trows = self._db.execute("SELECT name, data FROM gen_tables WHERE generator_id = ?", (rid,)).fetchall()
        return {n: GenTable.model_validate_json(d) for n, d in trows}

    def save(self, rid: str, name: str, gen: Generator) -> GenRecord:
        gen = gen.model_copy(update={"tables": {}})
        with self._lock, self._db:
            self._save(rid, name, gen)
        return self.get(rid)

    def _save(self, rid: str, name: str, gen: Generator) -> None:
        """Caller holds the lock and the transaction."""
        row = self._db.execute("SELECT name, data FROM gen_generators WHERE id = ?", (rid,)).fetchone()
        if not row:
            raise NotFound(rid)
        data = gen.model_dump_json()
        self._db.execute("UPDATE gen_generators SET name = ?, data = ?, updated_at = ? WHERE id = ?",
                         (name, data, _now().isoformat(), rid))
        audit.log(self._db, "generator", rid, {"name": row[0], **json.loads(row[1])}, {"name": name, **json.loads(data)},
                  label=name)

    def delete(self, rid: str) -> None:
        with self._lock, self._db:
            row = self._db.execute("SELECT name, kind, source_file FROM gen_generators WHERE id = ?", (rid,)).fetchone()
            if row:
                audit.log(self._db, "generator", rid, dict(zip(("name", "kind", "source_file"), row)), None)
            self._db.execute("DELETE FROM gen_generators WHERE id = ?", (rid,))

    def replace_tables(self, rid: str, tables: dict[str, GenTable]) -> None:
        self.get(rid)
        with self._lock, self._db:
            self._replace_tables(rid, tables)

    @staticmethod
    def _table_sizes(tables: dict[str, GenTable]) -> dict[str, str]:
        return {n: f"{len(t.rows)} row(s), {len(t.columns)} column(s)" for n, t in tables.items()}

    def _replace_tables(self, rid: str, tables: dict[str, GenTable]) -> None:
        """Caller holds the lock and the transaction. Lookup tables can be large, so the
        log keeps each table's size, not its contents."""
        old = {n: GenTable.model_validate_json(d) for n, d in self._db.execute(
            "SELECT name, data FROM gen_tables WHERE generator_id = ?", (rid,))}
        self._db.execute("DELETE FROM gen_tables WHERE generator_id = ?", (rid,))
        self._db.executemany("INSERT INTO gen_tables VALUES (?, ?, ?)",
                             [(rid, n, t.model_dump_json()) for n, t in tables.items()])
        changed = sorted(n for n in tables if n in old and old[n] != tables[n])
        (name,) = self._db.execute("SELECT name FROM gen_generators WHERE id = ?", (rid,)).fetchone()
        audit.log(self._db, "gen_tables", rid, self._table_sizes(old), self._table_sizes(tables), parent_id=rid,
                  label=f"{name}: lookup tables",
                  note=("contents changed in: " + ", ".join(changed)) if changed else None)

    def apply_import(self, rid: str, name: str, gen: Generator, tables: dict[str, GenTable] | None = None) -> None:
        """Save everything an inputs-workbook import changes in one transaction, so a
        failure (or a conflict) leaves nothing half-applied."""
        gen = gen.model_copy(update={"tables": {}})
        with self._lock, self._db:
            self._save(rid, name, gen)
            if tables is not None:
                self._replace_tables(rid, tables)

    # -- builds ------------------------------------------------------------------

    def add_build(self, info: BuildInfo, result: BuildResult) -> BuildInfo:
        with self._lock, self._db:
            (latest,) = self._db.execute("SELECT COALESCE(MAX(seq), 0) FROM gen_builds WHERE generator_id = ?",
                                         (info.generator_id,)).fetchone()
            info = info.model_copy(update={"seq": latest + 1})
            self._db.execute("INSERT INTO gen_builds VALUES (?, ?, ?, ?, ?)",
                             (info.id, info.generator_id, info.seq, info.model_dump_json(), result.model_dump_json()))
            audit.log(self._db, "gen_build", info.id, None, info.model_dump_json(), parent_id=info.generator_id,
                      label=f"Build {info.seq}")
        return info

    def list_builds(self, rid: str) -> list[BuildInfo]:
        with self._lock:
            rows = self._db.execute("SELECT info FROM gen_builds WHERE generator_id = ? ORDER BY seq DESC",
                                    (rid,)).fetchall()
        return [BuildInfo.model_validate_json(r[0]) for r in rows]

    def latest_build(self, rid: str) -> BuildRecord | None:
        with self._lock:
            row = self._db.execute("SELECT info, data FROM gen_builds WHERE generator_id = ? ORDER BY seq DESC LIMIT 1",
                                   (rid,)).fetchone()
        return None if not row else BuildRecord(info=BuildInfo.model_validate_json(row[0]),
                                                result=BuildResult.model_validate_json(row[1]))

    def get_build(self, bid: str) -> BuildRecord:
        with self._lock:
            row = self._db.execute("SELECT info, data FROM gen_builds WHERE id = ?", (bid,)).fetchone()
        if not row:
            raise NotFound(bid)
        return BuildRecord(info=BuildInfo.model_validate_json(row[0]), result=BuildResult.model_validate_json(row[1]))

    def delete_build(self, bid: str) -> None:
        with self._lock, self._db:
            row = self._db.execute("SELECT info, generator_id, seq FROM gen_builds WHERE id = ?", (bid,)).fetchone()
            if row:
                audit.log(self._db, "gen_build", bid, row[0], None, parent_id=row[1], label=f"Build {row[2]}")
            self._db.execute("DELETE FROM gen_builds WHERE id = ?", (bid,))

    def counts(self) -> tuple[int, int]:
        with self._lock:
            (g,) = self._db.execute("SELECT COUNT(*) FROM gen_generators").fetchone()
            (b,) = self._db.execute("SELECT COUNT(*) FROM gen_builds").fetchone()
        return g, b

    def all_builds(self) -> list[BuildInfo]:
        with self._lock:
            rows = self._db.execute("SELECT info FROM gen_builds").fetchall()
        return [BuildInfo.model_validate_json(r[0]) for r in rows]


def configure(data_dir: Path | None) -> None:
    """(Re)open the data folder: its project list and, on demand, each project's database."""
    from . import projects  # imported late: projects builds on this module

    projects.configure(data_dir)


def close() -> None:
    """Close the data folder's databases (see ``projects.close``)."""
    from . import projects

    projects.close()


def get_store() -> Store:
    """The store of the project the current request works in (see ``projects``)."""
    from . import projects

    return projects.current_store()


def get_ref() -> RefStore:
    return RefStore(get_store())


def get_deliverables() -> DeliverableStore:
    return DeliverableStore(get_store())


def get_loadlist() -> LoadListStore:
    return LoadListStore(get_store())


def get_keylists() -> KeyListStore:
    return KeyListStore(get_store())


def get_symbols() -> SymbolStore:
    return SymbolStore(get_store())


def get_generators() -> GeneratorStore:
    return GeneratorStore(get_store())
