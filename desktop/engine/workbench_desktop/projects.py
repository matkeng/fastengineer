# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Projects: each one is a folder with its own database (workbench.db) and drawings.

``<data dir>/registry.db`` lists the projects, who may open each one, and the
project each user had open last. A request names its project in the
``X-Workbench-Project`` header; ``storage.get_store()`` then returns that
project's store, so people work in different projects on one engine at once.

The data that existed before projects (``<data dir>/workbench.db``) is the
"Default" project and stays where it is.
"""

from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import audit, identity
from .storage import Store, default_data_dir

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    name_key TEXT NOT NULL UNIQUE,
    path TEXT NOT NULL,          -- '' = <data dir>/projects/<id>, '.' = the data dir itself, else a folder
    archived INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS members (
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_key TEXT NOT NULL,
    user TEXT NOT NULL,
    PRIMARY KEY (project_id, user_key)
);
-- Everyone who has started the app, and the project they had open last.
CREATE TABLE IF NOT EXISTS users (
    user_key TEXT PRIMARY KEY,
    user TEXT NOT NULL,
    last_project_id TEXT,
    last_seen TEXT NOT NULL
);
"""

#: Copied into a new project made "from" another one: the standards, not the work.
COPIED_TABLES = ("ref_names", "ref_enums", "ref_trees", "ref_tables", "ref_rows", "sym_libraries", "sym_templates")
COPIED_SETTINGS = ("gen_hw_catalogue", "symbols_seeded")


class ProjectError(Exception):
    """A problem to show the user as it is (``status`` is the HTTP status)."""

    def __init__(self, status: int, message: str, field: str | None = None):
        super().__init__(message)
        self.status, self.message, self.field = status, message, field


def user_key(user: str) -> str:
    """Windows logins are not case sensitive."""
    return user.strip().casefold()


def is_admin(user: str) -> bool:
    """On a shared server, the names given with --admin. On your own PC, you."""
    return not identity.server_mode or user_key(user) in identity.admins


def enforced() -> bool:
    """Membership applies on a shared server that has administrators. Without any
    administrator nobody could add members, so every project is open to everyone."""
    return identity.server_mode and bool(identity.admins)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Registry:
    def __init__(self, root: Path):
        root.mkdir(parents=True, exist_ok=True)
        self.root = root
        self._lock = threading.RLock()
        self._db = sqlite3.connect(root / "registry.db", check_same_thread=False)
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.execute("PRAGMA busy_timeout = 5000")
        self._db.executescript(SCHEMA)
        self._db.executescript(audit.SCHEMA)
        self._stores: dict[str, Store] = {}
        if not self._db.execute("SELECT 1 FROM projects").fetchone():
            self._adopt_existing()

    def close(self) -> None:
        with self._lock:
            for store in self._stores.values():
                store._db.close()
            self._stores.clear()
            self._db.close()

    def _adopt_existing(self) -> None:
        """First start with projects: the data folder as it is becomes "Default"."""
        had_data = (self.root / "workbench.db").exists()
        with self._lock, self._db:
            self._db.execute("INSERT INTO projects VALUES ('default', 'Default', 'default', '.', 0, ?, 'system')", (_now(),))
        if had_data and identity.server_mode:
            # Whoever already worked in it keeps access.
            store = self.store("default")
            with self._lock, self._db:
                for user in store.audit_users():
                    self._db.execute("INSERT OR IGNORE INTO members VALUES ('default', ?, ?)", (user_key(user), user))

    # -- reading ---------------------------------------------------------------

    def folder(self, path: str, project_id: str) -> Path:
        if path == ".":
            return self.root
        return Path(path) if path else self.root / "projects" / project_id

    def _row(self, row) -> dict:
        pid, name, path, archived, created_at, created_by = row
        members = [r[0] for r in self._db.execute("SELECT user FROM members WHERE project_id = ? ORDER BY user_key", (pid,))]
        return {"id": pid, "name": name, "archived": bool(archived), "folder": str(self.folder(path, pid)),
                "members": members, "created_at": created_at, "created_by": created_by}

    def all(self) -> list[dict]:
        with self._lock:
            rows = self._db.execute("SELECT id, name, path, archived, created_at, created_by FROM projects "
                                    "ORDER BY archived, name_key").fetchall()
            return [self._row(r) for r in rows]

    def get(self, project_id: str) -> dict:
        with self._lock:
            row = self._db.execute("SELECT id, name, path, archived, created_at, created_by FROM projects WHERE id = ?",
                                   (project_id,)).fetchone()
            if not row:
                raise ProjectError(404, "That project no longer exists.")
            return self._row(row)

    def may_open(self, project: dict, user: str) -> bool:
        if project["archived"]:
            return False
        return not enforced() or is_admin(user) or user_key(user) in {user_key(m) for m in project["members"]}

    def for_user(self, user: str) -> list[dict]:
        return [p for p in self.all() if self.may_open(p, user)]

    def default_for(self, user: str) -> str | None:
        """The project the user had open last, else the first one they may open."""
        mine = self.for_user(user)
        with self._lock:
            row = self._db.execute("SELECT last_project_id FROM users WHERE user_key = ?", (user_key(user),)).fetchone()
        if row and any(p["id"] == row[0] for p in mine):
            return row[0]
        return mine[0]["id"] if mine else None

    def known_users(self) -> list[str]:
        with self._lock:
            rows = self._db.execute("SELECT user_key, user FROM users UNION SELECT user_key, user FROM members").fetchall()
        return sorted(dict(rows).values(), key=str.casefold)

    def log_entries(self, **filters) -> list[dict]:
        with self._lock:
            return audit.entries(self._db, **filters)

    # -- per user ----------------------------------------------------------------

    def seen(self, user: str, project_id: str | None = None) -> None:
        """Note that the user started the app and, when given, which project they opened."""
        if not user or user == "unknown":
            return
        with self._lock, self._db:
            self._db.execute("INSERT INTO users VALUES (?, ?, ?, ?) ON CONFLICT(user_key) DO UPDATE SET "
                             "user = excluded.user, last_seen = excluded.last_seen, "
                             "last_project_id = COALESCE(excluded.last_project_id, last_project_id)",
                             (user_key(user), user, project_id, _now()))

    # -- stores ------------------------------------------------------------------

    def store(self, project_id: str) -> Store:
        with self._lock:
            store = self._stores.get(project_id)
            if store is None:
                row = self._db.execute("SELECT path FROM projects WHERE id = ?", (project_id,)).fetchone()
                if not row:
                    raise ProjectError(404, "That project no longer exists.")
                store = self._stores[project_id] = Store(self.folder(row[0], project_id) / "workbench.db")
            return store

    # -- changing (administrators) -------------------------------------------------

    @staticmethod
    def _logged(project: dict) -> dict:
        return {k: project[k] for k in ("name", "folder", "archived", "members")}

    def _check_name(self, name: str, project_id: str | None = None) -> str:
        name = " ".join(name.split())
        if not name:
            raise ProjectError(422, "Give the project a name.", "name")
        row = self._db.execute("SELECT id FROM projects WHERE name_key = ?", (name.casefold(),)).fetchone()
        if row and row[0] != project_id:
            raise ProjectError(422, f"There is already a project called '{name}'.", "name")
        return name

    def _check_folder(self, path: str) -> Path:
        text = path.strip()
        if text.startswith(("\\\\", "//")):
            raise ProjectError(422, "Use a folder on a local disk of this machine, not a network share: "
                                    "the database is not safe on a share.", "path")
        folder = Path(text)
        if not folder.is_absolute():
            raise ProjectError(422, "Give the full path of the folder, e.g. D:\\Projects\\Plant A.", "path")
        folder = folder.resolve()
        for p in self.all():
            if Path(p["folder"]).resolve() == folder:
                raise ProjectError(422, f"The project '{p['name']}' already uses that folder.", "path")
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ProjectError(422, f"Can't create that folder: {exc.strerror or exc}", "path") from exc
        return folder

    def _set_members(self, project_id: str, members: list[str]) -> None:
        self._db.execute("DELETE FROM members WHERE project_id = ?", (project_id,))
        for user in members:
            if user.strip():
                self._db.execute("INSERT OR IGNORE INTO members VALUES (?, ?, ?)", (project_id, user_key(user), user.strip()))

    def create(self, name: str, path: str | None = None, copy_from: str | None = None,
               members: list[str] | None = None) -> dict:
        """A new project. With ``path``, in that folder (a database already there is
        opened as it is); with ``copy_from``, starting with that project's lists, trees,
        tables, symbol libraries and card and rack types."""
        user = identity.current().user
        with self._lock:
            name = self._check_name(name)
            source = self.get(copy_from) if copy_from else None
            project_id = uuid.uuid4().hex
            folder = self._check_folder(path) if path and path.strip() else None
            existing = bool(folder and (folder / "workbench.db").exists())
            if existing and source:
                raise ProjectError(422, "That folder already has a project database, so nothing can be copied "
                                        "into it. Choose 'start empty' to open it as it is.", "copy_from")
            with self._db:
                self._db.execute("INSERT INTO projects VALUES (?, ?, ?, ?, 0, ?, ?)",
                                 (project_id, name, name.casefold(), str(folder) if folder else "", _now(), user))
                self._set_members(project_id, members or [])
                project = self.get(project_id)
                audit.log(self._db, "project", project_id, None, self._logged(project), label=name,
                          note="opened the database already in that folder" if existing
                          else f"standards copied from '{source['name']}'" if source else None)
            store = self.store(project_id)
            if source:
                self._copy_standards(self.store(source["id"]), store, source["name"])
            return project

    def _copy_standards(self, source: Store, target: Store, source_name: str) -> None:
        with source._lock:
            source._db.execute("PRAGMA wal_checkpoint(FULL)")  # so the attached copy sees every saved change
        with target._lock:
            target._db.execute("ATTACH DATABASE ? AS src", (str(source.path),))
            try:
                with target._db:
                    counts = {}
                    for table in COPIED_TABLES:
                        cur = target._db.execute(f"INSERT INTO main.{table} SELECT * FROM src.{table}")
                        counts[table] = cur.rowcount
                    marks = ", ".join("?" for _ in COPIED_SETTINGS)
                    target._db.execute(f"INSERT OR REPLACE INTO main.settings SELECT * FROM src.settings "
                                       f"WHERE key IN ({marks})", COPIED_SETTINGS)
                    audit.log(target._db, "project", "standards", None,
                              {"lists": counts["ref_enums"], "trees": counts["ref_trees"], "tables": counts["ref_tables"],
                               "table rows": counts["ref_rows"], "symbol libraries": counts["sym_libraries"],
                               "symbol templates": counts["sym_templates"]},
                              label=f"Standards copied from '{source_name}'")
            finally:
                target._db.execute("DETACH DATABASE src")

    def update(self, project_id: str, name: str | None = None, archived: bool | None = None,
               members: list[str] | None = None) -> dict:
        with self._lock:
            before = self.get(project_id)
            with self._db:
                if name is not None:
                    name = self._check_name(name, project_id)
                    self._db.execute("UPDATE projects SET name = ?, name_key = ? WHERE id = ?",
                                     (name, name.casefold(), project_id))
                if archived is not None:
                    if archived and sum(1 for p in self.all() if not p["archived"]) <= 1 and not before["archived"]:
                        raise ProjectError(422, "This is the only project in use, so it can't be archived.")
                    self._db.execute("UPDATE projects SET archived = ? WHERE id = ?", (int(archived), project_id))
                if members is not None:
                    self._set_members(project_id, members)
                after = self.get(project_id)
                audit.log(self._db, "project", project_id, self._logged(before), self._logged(after), label=after["name"])
            return after


_registry: Registry | None = None


def configure(data_dir: Path | None) -> Registry:
    global _registry
    if _registry is not None:
        _registry.close()
    _registry = Registry(data_dir or default_data_dir())
    return _registry


def registry() -> Registry:
    return _registry or configure(None)


def current_store() -> Store:
    """The store of the project this request (or background job) works in."""
    ctx = identity.current()
    reg = registry()
    project_id = ctx.project or reg.default_for(ctx.user)
    if project_id is None:
        raise ProjectError(403, "You have not been added to a project yet. Ask an administrator.")
    return reg.store(project_id)


#: Requests that work without a project (finding out who you are and which projects you have).
_NO_PROJECT = ("/api/projects", "/api/health", "/api/info", "/api/whoami", "/api/hello", "/api/model")


def resolve(ctx: identity.RequestContext, path: str, requested: str | None) -> None:
    """Set ``ctx.project`` for a request, or raise ProjectError if the user may not use it."""
    reg = registry()
    needs = path.startswith("/api/") and not path.startswith(_NO_PROJECT)
    if requested:
        try:
            project = reg.get(requested)
        except ProjectError:
            if needs:
                raise
            return
        if reg.may_open(project, ctx.user):
            ctx.project = project["id"]
        elif needs:
            raise ProjectError(403, f"The project '{project['name']}' has been archived." if project["archived"]
                               else f"You are not a member of the project '{project['name']}'. Ask an administrator.")
        return
    ctx.project = reg.default_for(ctx.user)
    if ctx.project is None and needs:
        raise ProjectError(403, "You have not been added to a project yet. Ask an administrator.")
