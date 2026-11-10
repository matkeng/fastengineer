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

from workbench_core.keylists import EquipmentPackageList, LoadTypeList, PlantAreaList
from workbench_core.mel import Recipe, Revision
from workbench_core.refdata import EnumList, RefRow, RefTable, RefTree, RefValidationError, name_key
from workbench_core.mel.models import RevisionInfo
from workbench_core.symbols import Drawing, Library, PageOverride, PageResult, PageReview, RunInfo, Template
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
-- PLC hardware register per generator (panels -> racks -> cards); the type catalogue is in settings.
CREATE TABLE IF NOT EXISTS gen_hardware (
    generator_id TEXT PRIMARY KEY REFERENCES gen_generators(id) ON DELETE CASCADE,
    data TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    data TEXT NOT NULL
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
                     warnings: list[str]) -> RevisionInfo:
        self.get_recipe(recipe_id)  # 404 if missing
        with self._lock, self._db:
            (latest,) = self._db.execute("SELECT COALESCE(MAX(rev), 0) FROM revisions WHERE recipe_id = ?",
                                         (recipe_id,)).fetchone()
            info = RevisionInfo(id=uuid.uuid4().hex, rev=latest + 1, file_name=file_name, source=source,
                                key_header=key_header, num_rows=len(rows), num_cols=len(headers),
                                uploaded_at=_now(), warnings=warnings)
            data = json.dumps({"headers": headers, "headers_original": headers_original, "rows": rows})
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

    def __init__(self, store: Store):
        self._db = store._db
        self._lock = store._lock

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

    def load_types(self) -> LoadTypeList:
        with self._lock:
            row = self._db.execute("SELECT data FROM key_lists WHERE id = ?", (self.LOAD_TYPES,)).fetchone()
        return LoadTypeList.model_validate_json(row[0]) if row else LoadTypeList()

    def save_load_types(self, loads: LoadTypeList) -> LoadTypeList:
        loads = loads.model_copy(update={"updated_at": _now()})
        with self._lock, self._db:
            before = audit.data_of(self._db, "key_lists", "id = ?", (self.LOAD_TYPES,))
            self._db.execute("INSERT INTO key_lists VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET data = excluded.data",
                             (self.LOAD_TYPES, loads.model_dump_json()))
            audit.log(self._db, "load_types", self.LOAD_TYPES, before or LoadTypeList().model_dump_json(),
                      loads.model_dump_json(), label="Load Types")
        return loads


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
            png, mask = self.template_image(t.id), self.template_mask(t.id)
            with self._lock, self._db:
                audit.check(self._db, "sym_template", t.id)
                self._db.execute("DELETE FROM sym_templates WHERE id = ?", (t.id,))
                self._renumber(old.library_id)
            new = self.add_template(t.model_copy(update={"width": old.width, "height": old.height}), png, mask, log=False)
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

    def apply_import(self, rid: str, name: str, gen: Generator, tables: dict[str, GenTable] | None = None,
                     hardware: Hardware | None = None, catalogue: Catalogue | None = None) -> None:
        """Save everything an inputs-workbook import changes in one transaction, so a
        failure (or a conflict) leaves nothing half-applied."""
        gen = gen.model_copy(update={"tables": {}})
        with self._lock, self._db:
            self._save(rid, name, gen)
            if tables is not None:
                self._replace_tables(rid, tables)
            if hardware is not None:
                self._save_hardware(rid, hardware)
            if catalogue is not None:
                self._save_catalogue(catalogue)

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

    # -- PLC hardware ----------------------------------------------------------------

    def catalogue(self) -> Catalogue:
        with self._lock:
            row = self._db.execute("SELECT data FROM settings WHERE key = 'gen_hw_catalogue'").fetchone()
        return Catalogue.model_validate_json(row[0]) if row else default_catalogue()

    def save_catalogue(self, cat: Catalogue) -> Catalogue:
        with self._lock, self._db:
            self._save_catalogue(cat)
        return cat

    def _save_catalogue(self, cat: Catalogue) -> None:
        """Caller holds the lock and the transaction."""
        before = audit.data_of(self._db, "settings", "key = ?", ("gen_hw_catalogue",))
        self._db.execute("INSERT INTO settings VALUES ('gen_hw_catalogue', ?) "
                         "ON CONFLICT(key) DO UPDATE SET data = excluded.data", (cat.model_dump_json(),))
        # Before the first save the built-in defaults are in effect, so that is what changed.
        audit.log(self._db, "gen_catalogue", "catalogue", before or default_catalogue().model_dump_json(),
                  cat.model_dump_json(), label="Card and rack types")

    def hardware(self, rid: str) -> Hardware:
        self.get(rid)
        with self._lock:
            row = self._db.execute("SELECT data FROM gen_hardware WHERE generator_id = ?", (rid,)).fetchone()
        return Hardware.model_validate_json(row[0]) if row else Hardware()

    def save_hardware(self, rid: str, hw: Hardware) -> Hardware:
        self.get(rid)
        with self._lock, self._db:
            self._save_hardware(rid, hw)
        return hw

    def _save_hardware(self, rid: str, hw: Hardware) -> None:
        """Caller holds the lock and the transaction."""
        before = audit.data_of(self._db, "gen_hardware", "generator_id = ?", (rid,))
        self._db.execute("INSERT INTO gen_hardware VALUES (?, ?, ?) ON CONFLICT(generator_id) DO UPDATE SET "
                         "data = excluded.data, updated_at = excluded.updated_at",
                         (rid, hw.model_dump_json(), _now().isoformat()))
        (name,) = self._db.execute("SELECT name FROM gen_generators WHERE id = ?", (rid,)).fetchone()
        audit.log(self._db, "gen_hardware", rid, before or Hardware().model_dump_json(), hw.model_dump_json(),
                  parent_id=rid, label=f"{name}: PLC hardware")

    def hardware_counts(self) -> tuple[int, int]:
        """(panels, cards) across all generators."""
        with self._lock:
            rows = self._db.execute("SELECT data FROM gen_hardware").fetchall()
        panels = cards = 0
        for (d,) in rows:
            hw = Hardware.model_validate_json(d)
            panels += len(hw.panels)
            cards += sum(1 for p in hw.panels for r in p.racks for c in r.cards if c is not None)
        return panels, cards

    def all_builds(self) -> list[BuildInfo]:
        with self._lock:
            rows = self._db.execute("SELECT info FROM gen_builds").fetchall()
        return [BuildInfo.model_validate_json(r[0]) for r in rows]


def configure(data_dir: Path | None) -> None:
    """(Re)open the data folder: its project list and, on demand, each project's database."""
    from . import projects  # imported late: projects builds on this module

    projects.configure(data_dir)


def get_store() -> Store:
    """The store of the project the current request works in (see ``projects``)."""
    from . import projects

    return projects.current_store()


def get_ref() -> RefStore:
    return RefStore(get_store())


def get_keylists() -> KeyListStore:
    return KeyListStore(get_store())


def get_symbols() -> SymbolStore:
    return SymbolStore(get_store())


def get_generators() -> GeneratorStore:
    return GeneratorStore(get_store())
