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

from workbench_core.mel import Recipe, Revision
from workbench_core.refdata import EnumList, RefRow, RefTable, RefValidationError, name_key
from workbench_core.mel.models import RevisionInfo
from workbench_core.symbols import Drawing, Library, PageOverride, PageResult, RunInfo, Template

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
CREATE TABLE IF NOT EXISTS sym_runs (
    id TEXT PRIMARY KEY,
    info TEXT NOT NULL,
    sheets TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
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
        self._db.executescript(SCHEMA)

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
            cur = self._db.execute("UPDATE recipes SET name = ?, target = ?, data = ?, updated_at = ? WHERE id = ?",
                                   (recipe.name, recipe.target, recipe.model_dump_json(),
                                    recipe.updated_at.isoformat(), recipe.id))
        if cur.rowcount == 0:
            raise NotFound(recipe.id)
        return recipe

    def delete_recipe(self, recipe_id: str) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM recipes WHERE id = ?", (recipe_id,))

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
            self._db.execute("DELETE FROM revisions WHERE id = ? AND recipe_id = ?", (revision_id, recipe_id))


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
            table = "ref_enums" if kind == "enum" else "ref_tables"
            data = self._db.execute(f"SELECT data FROM {table} WHERE id = ?", (other,)).fetchone()
            existing = json.loads(data[0])["name"] if data else name
            what = "list" if kind == "enum" else "table"
            raise RefValidationError(f"There is already a {what} called '{existing}'. Names must be unique "
                                     "across lists and tables (ignoring case).", {"name": "Name already used"})
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
            if not create and not self._db.execute("SELECT 1 FROM ref_enums WHERE id = ?", (enum.id,)).fetchone():
                raise NotFound(enum.id)
            self._claim_name("enum", enum.id, enum.name)
            self._db.execute("INSERT INTO ref_enums VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET data = excluded.data",
                             (enum.id, enum.model_dump_json()))
        return enum

    def delete_enum(self, enum_id: str) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM ref_enums WHERE id = ?", (enum_id,))
            self._db.execute("DELETE FROM ref_names WHERE object_id = ?", (enum_id,))

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
            if not create and not self._db.execute("SELECT 1 FROM ref_tables WHERE id = ?", (table.id,)).fetchone():
                raise NotFound(table.id)
            self._claim_name("table", table.id, table.name)
            # Upsert, not INSERT OR REPLACE: REPLACE deletes first, which would cascade to the rows.
            self._db.execute("INSERT INTO ref_tables VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET data = excluded.data",
                             (table.id, table.model_dump_json()))
            for r in rows or []:
                self._db.execute("UPDATE ref_rows SET data = ? WHERE id = ?", (r.model_dump_json(), r.id))
        return table

    def delete_table(self, table_id: str) -> None:
        with self._lock, self._db:
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
        return row

    def update_row(self, table_id: str, row: RefRow) -> RefRow:
        row = row.model_copy(update={"updated_at": _now()})
        with self._lock, self._db:
            cur = self._db.execute("UPDATE ref_rows SET data = ? WHERE id = ? AND table_id = ?",
                                   (row.model_dump_json(), row.id, table_id))
        if cur.rowcount == 0:
            raise NotFound(row.id)
        return row

    def delete_row(self, table_id: str, row_id: str) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM ref_rows WHERE id = ? AND table_id = ?", (row_id, table_id))


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
                else:
                    cur = self._db.execute("UPDATE sym_libraries SET name_key = ?, data = ? WHERE id = ?",
                                           (name_key(lib.name), lib.model_dump_json(), lib.id))
                    if cur.rowcount == 0:
                        raise NotFound(lib.id)
        except sqlite3.IntegrityError as exc:
            raise RefValidationError(f"There is already a library called '{lib.name}'.", {"name": "Already used."}) from exc
        return lib

    def delete_library(self, library_id: str) -> None:
        with self._lock:
            (n,) = self._db.execute("SELECT COUNT(*) FROM sym_drawings WHERE library_id = ?", (library_id,)).fetchone()
        if n:
            raise InUse(f"{n} drawing(s) use this library. Move them to another library or remove them first.")
        with self._lock, self._db:
            self._db.execute("DELETE FROM sym_libraries WHERE id = ?", (library_id,))

    # -- drawings --------------------------------------------------------------

    def add_drawing(self, drawing: Drawing, pdf: bytes) -> Drawing:
        d = self.doc_dir(drawing.id)
        d.mkdir(parents=True, exist_ok=True)
        (d / "source.pdf").write_bytes(pdf)
        with self._lock, self._db:
            self._db.execute("INSERT INTO sym_drawings VALUES (?, ?, ?, ?)",
                             (drawing.id, drawing.library_id, drawing.model_dump_json(), _now().isoformat()))
        return drawing

    def save_drawing(self, drawing: Drawing) -> Drawing:
        with self._lock, self._db:
            cur = self._db.execute("UPDATE sym_drawings SET library_id = ?, data = ? WHERE id = ?",
                                   (drawing.library_id, drawing.model_dump_json(), drawing.id))
        if cur.rowcount == 0:
            raise NotFound(drawing.id)
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

    def add_template(self, t: Template, png: bytes, mask: bytes | None = None) -> Template:
        """Append to the end of its library's priority list."""
        self.get_library(t.library_id)
        with self._lock, self._db:
            (count,) = self._db.execute("SELECT COUNT(*) FROM sym_templates WHERE library_id = ?",
                                        (t.library_id,)).fetchone()
            t = t.model_copy(update={"priority": count, "has_custom_mask": mask is not None})
            self._db.execute("INSERT INTO sym_templates VALUES (?, ?, ?, ?, ?, ?)",
                             (t.id, t.library_id, t.priority, t.model_dump_json(), png, mask))
        return t

    def save_template(self, t: Template) -> Template:
        """Edit fields. Moving library re-appends it there; priority changes go through move."""
        old = self.get_template(t.id)
        if old.library_id != t.library_id:
            png, mask = self.template_image(t.id), self.template_mask(t.id)
            with self._lock, self._db:
                self._db.execute("DELETE FROM sym_templates WHERE id = ?", (t.id,))
                self._renumber(old.library_id)
            return self.add_template(t.model_copy(update={"width": old.width, "height": old.height}), png, mask)
        t = t.model_copy(update={"priority": old.priority, "width": old.width, "height": old.height,
                                 "has_custom_mask": old.has_custom_mask})
        with self._lock, self._db:
            self._db.execute("UPDATE sym_templates SET data = ? WHERE id = ?", (t.model_dump_json(), t.id))
        return t

    def set_template_mask(self, template_id: str, mask: bytes | None) -> Template:
        t = self.get_template(template_id).model_copy(update={"has_custom_mask": mask is not None})
        if mask is None and t.mask_mode == "custom":
            t.mask_mode = "auto"
        elif mask is not None:
            t.mask_mode = "custom"
        with self._lock, self._db:
            self._db.execute("UPDATE sym_templates SET mask = ?, data = ? WHERE id = ?", (mask, t.model_dump_json(), t.id))
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
        return self.get_template(template_id)

    def delete_template(self, template_id: str) -> None:
        t = self.get_template(template_id)
        with self._lock, self._db:
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
            self._db.execute("INSERT INTO sym_overrides VALUES (?, ?, ?, ?) ON CONFLICT(doc_id, page, template_id) "
                             "DO UPDATE SET data = excluded.data", (doc_id, page, ov.template_id, ov.model_dump_json()))
        return ov

    def delete_override(self, doc_id: str, page: int, template_id: str) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM sym_overrides WHERE doc_id = ? AND page = ? AND template_id = ?",
                             (doc_id, page, template_id))

    def save_result(self, doc_id: str, result: PageResult) -> None:
        with self._lock, self._db:
            self._db.execute("INSERT INTO sym_results VALUES (?, ?, ?) ON CONFLICT(doc_id, page) "
                             "DO UPDATE SET data = excluded.data", (doc_id, result.page, result.model_dump_json()))

    def result(self, doc_id: str, page: int) -> PageResult | None:
        with self._lock:
            row = self._db.execute("SELECT data FROM sym_results WHERE doc_id = ? AND page = ?", (doc_id, page)).fetchone()
        return PageResult.model_validate_json(row[0]) if row else None

    # -- runs ------------------------------------------------------------------

    def save_run(self, run: RunInfo, sheets: list[dict] | None = None) -> RunInfo:
        with self._lock, self._db:
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

    def delete_run(self, run_id: str) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM sym_runs WHERE id = ?", (run_id,))

    # -- first run -------------------------------------------------------------

    def seeded(self) -> bool:
        with self._lock:
            return self._db.execute("SELECT 1 FROM settings WHERE key = 'symbols_seeded'").fetchone() is not None

    def mark_seeded(self) -> None:
        with self._lock, self._db:
            self._db.execute("INSERT INTO settings VALUES ('symbols_seeded', '1') ON CONFLICT(key) DO NOTHING")


_store: Store | None = None


def configure(data_dir: Path | None) -> Store:
    global _store
    if _store is not None:
        _store._db.close()
    _store = Store((data_dir or default_data_dir()) / "workbench.db")
    return _store


def get_store() -> Store:
    return _store or configure(None)


def get_ref() -> RefStore:
    return RefStore(get_store())


def get_symbols() -> SymbolStore:
    return SymbolStore(get_store())
