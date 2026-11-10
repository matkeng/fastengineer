# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Projects: each one is a self-contained folder.

A project folder holds ``workbench.db`` (and the drawings beside it), and that
database holds everything about the project: its data, its change log, and its
own name, id, members and archived flag. There is no central list of projects,
so a folder can be copied, moved, backed up or opened by another engine and it
brings all of that with it.

An engine serves every project folder it finds:

- its data folder itself (the "Default" project, where data lived before projects),
- each folder under ``<data dir>/projects/``,
- folders elsewhere that an administrator has pointed it at.

``<data dir>/engine.db`` is the engine's own notebook, not project data: those
extra folder locations, and the project each user had open last.

A request names its project in the ``X-Workbench-Project`` header;
``storage.get_store()`` then returns that project's store.
"""

from __future__ import annotations

import re
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import audit, identity
from .storage import Store, default_data_dir

SCHEMA = """
-- Project folders outside <data dir>/projects that this engine also serves.
CREATE TABLE IF NOT EXISTS locations (
    path TEXT PRIMARY KEY
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


@dataclass
class Entry:
    """One project this engine serves. ``meta`` mirrors what is saved in the project's own database."""
    store: Store
    folder: Path
    external: bool      # outside the data folder: the engine only holds a pointer to it
    meta: dict          # id, name, archived, members, created_at, created_by


def _safe_folder_name(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", name).strip(" .") or "Project"


class Registry:
    """The projects this engine serves. (Not a database of projects: each project's
    details live in its own folder; this only finds the folders and opens them.)"""

    def __init__(self, root: Path):
        root.mkdir(parents=True, exist_ok=True)
        self.root = root
        self._lock = threading.RLock()
        self._db = sqlite3.connect(root / "engine.db", check_same_thread=False)
        self._db.execute("PRAGMA busy_timeout = 5000")
        self._db.executescript(SCHEMA)
        self._projects: dict[str, Entry] = {}
        #: Pointed-at folders that are not there (moved, or a disk that is not connected).
        self.missing: list[str] = []
        legacy = self._read_legacy_registry()
        self._open(root, external=False, legacy=legacy, default=True)
        for folder in sorted((root / "projects").glob("*/")):
            if (folder / "workbench.db").exists():
                self._open(folder, external=False, legacy=legacy)
        for (path,) in self._db.execute("SELECT path FROM locations ORDER BY path").fetchall():
            if (Path(path) / "workbench.db").exists():
                self._open(Path(path), external=True, legacy=legacy)
            else:
                self.missing.append(path)

    def close(self) -> None:
        with self._lock:
            for entry in self._projects.values():
                entry.store._db.close()
            self._projects.clear()
            self._db.close()

    # -- finding and opening folders ------------------------------------------------

    def _read_legacy_registry(self) -> dict[str, dict]:
        """An earlier version kept project names and members centrally in registry.db.
        Read them once (by folder) so each project's own database can take them over."""
        old = self.root / "registry.db"
        if not old.exists():
            return {}
        out: dict[str, dict] = {}
        db = sqlite3.connect(old)
        try:
            for pid, name, path, archived, created_at, created_by in db.execute(
                    "SELECT id, name, path, archived, created_at, created_by FROM projects"):
                folder = self.root if path == "." else Path(path) if path else self.root / "projects" / pid
                members = [r[0] for r in db.execute("SELECT user FROM members WHERE project_id = ? ORDER BY user_key", (pid,))]
                out[str(folder.resolve())] = {"id": pid, "name": name, "archived": bool(archived), "members": members,
                                              "created_at": created_at, "created_by": created_by}
                if path not in ("", "."):
                    with self._db:
                        self._db.execute("INSERT OR IGNORE INTO locations VALUES (?)", (str(folder),))
            with self._db:
                self._db.executemany("INSERT OR IGNORE INTO users VALUES (?, ?, ?, ?)",
                                     db.execute("SELECT user_key, user, last_project_id, last_seen FROM users").fetchall())
        except sqlite3.Error:
            return {}
        finally:
            db.close()
        old.rename(old.with_name("registry.db.migrated"))
        return out

    def _open(self, folder: Path, *, external: bool, legacy: dict[str, dict] | None = None,
              default: bool = False) -> Entry:
        """Serve the project in ``folder``. A database that does not know its own
        details yet (from before projects, or brand new) is given them here."""
        had_data = (folder / "workbench.db").exists()
        store = Store(folder / "workbench.db")
        meta = store.project_meta()
        fresh = meta is None
        if meta is None:
            meta = (legacy or {}).get(str(folder.resolve())) or {
                "id": "default" if default else uuid.uuid4().hex,
                "name": "Default" if default else folder.name,
                "archived": False,
                # Whoever already worked in it keeps access.
                "members": store.audit_users() if had_data and identity.server_mode else [],
                "created_at": _now(), "created_by": "system"}
        if meta["id"] in self._projects:
            # The same project twice: this folder is a copy, so it becomes a project of its own.
            meta, fresh = {**meta, "id": uuid.uuid4().hex}, True
        if fresh:
            store.save_project_meta(meta, log=False)
        entry = self._projects[meta["id"]] = Entry(store, folder, external, meta)
        return entry

    # -- reading ---------------------------------------------------------------

    @staticmethod
    def _view(entry: Entry) -> dict:
        return {**entry.meta, "folder": str(entry.folder), "external": entry.external}

    def _entry(self, project_id: str) -> Entry:
        entry = self._projects.get(project_id)
        if entry is None:
            raise ProjectError(404, "That project no longer exists.")
        return entry

    def all(self) -> list[dict]:
        with self._lock:
            return sorted((self._view(e) for e in self._projects.values()),
                          key=lambda p: (p["archived"], p["name"].casefold(), p["folder"]))

    def get(self, project_id: str) -> dict:
        with self._lock:
            return self._view(self._entry(project_id))

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
            names = {user_key(u): u for (u,) in self._db.execute("SELECT user FROM users")}
            for entry in self._projects.values():
                names.update({user_key(m): m for m in entry.meta["members"]})
        return sorted(names.values(), key=str.casefold)

    def log_entries(self, limit: int = 100) -> list[dict]:
        """Who created, renamed or archived projects and changed their members: each
        project keeps this in its own change log; here they are put together."""
        with self._lock:
            entries = [e for entry in self._projects.values()
                       for e in entry.store.audit_entries(entity="project", limit=limit)]
        return sorted(entries, key=lambda e: e["at"], reverse=True)[:limit]

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

    def store(self, project_id: str) -> Store:
        with self._lock:
            return self._entry(project_id).store

    # -- changing (administrators) -------------------------------------------------

    def _check_name(self, name: str, project_id: str | None = None) -> str:
        name = " ".join(name.split())
        if not name:
            raise ProjectError(422, "Give the project a name.", "name")
        if any(e.meta["name"].casefold() == name.casefold() and pid != project_id for pid, e in self._projects.items()):
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
        for entry in self._projects.values():
            if entry.folder.resolve() == folder:
                raise ProjectError(422, f"The project '{entry.meta['name']}' already uses that folder.", "path")
        return folder

    @staticmethod
    def _members(members: list[str] | None) -> list[str]:
        out: dict[str, str] = {}
        for m in members or []:
            if m.strip():
                out.setdefault(user_key(m), m.strip())
        return sorted(out.values(), key=str.casefold)

    def create(self, name: str, path: str | None = None, copy_from: str | None = None,
               members: list[str] | None = None) -> dict:
        """A new project, in its own new folder: ``path`` if given, else one named after
        it under ``<data dir>/projects``. With ``copy_from`` it starts with that project's
        lists, trees, tables, symbol libraries and card and rack types."""
        user = identity.current().user
        with self._lock:
            name = self._check_name(name)
            source = self._entry(copy_from) if copy_from else None
            if path and path.strip():
                folder, external = self._check_folder(path), True
                if (folder / "workbench.db").exists():
                    raise ProjectError(422, "That folder already holds a project. Use 'Open an existing project "
                                            "folder' to add it as it is.", "path")
            else:
                base = self.root / "projects" / _safe_folder_name(name)
                folder, n, external = base, 2, False
                while folder.exists():
                    folder, n = base.with_name(f"{base.name} ({n})"), n + 1
            try:
                folder.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise ProjectError(422, f"Can't create that folder: {exc.strerror or exc}", "path") from exc
            store = Store(folder / "workbench.db")
            meta = {"id": uuid.uuid4().hex, "name": name, "archived": False, "members": self._members(members),
                    "created_at": _now(), "created_by": user}
            store.save_project_meta(meta, note=f"standards copied from '{source.meta['name']}'" if source else None)
            entry = self._projects[meta["id"]] = Entry(store, folder, external, meta)
            if external:
                with self._db:
                    self._db.execute("INSERT OR IGNORE INTO locations VALUES (?)", (str(folder),))
            if source:
                self._copy_standards(source.store, store, source.meta["name"])
            return self._view(entry)

    def attach(self, path: str) -> dict:
        """Serve a project folder that already exists (moved here, restored from a backup,
        or copied from another PC). It keeps its own name, members and history."""
        with self._lock:
            folder = self._check_folder(path)
            if not (folder / "workbench.db").exists():
                raise ProjectError(422, "There is no project in that folder (no workbench.db).", "path")
            inside = folder.parent == (self.root / "projects").resolve()
            entry = self._open(folder, external=not inside)
            if not inside:
                with self._db:
                    self._db.execute("INSERT OR IGNORE INTO locations VALUES (?)", (str(folder),))
            self.missing = [m for m in self.missing if Path(m).resolve() != folder]
            return self._view(entry)

    def detach(self, project_id: str) -> None:
        """Stop serving a project kept outside the data folder. The folder is left as it is."""
        with self._lock:
            entry = self._entry(project_id)
            if not entry.external:
                raise ProjectError(422, "This project is kept in the engine's own data folder, so it is always "
                                        "listed. Archive it to hide it.")
            entry.store._db.close()
            del self._projects[project_id]
            with self._db:
                self._db.execute("DELETE FROM locations WHERE path = ?", (str(entry.folder),))

    def forget_missing(self, path: str) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM locations WHERE path = ?", (path,))
            self.missing = [m for m in self.missing if m != path]

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
            entry = self._entry(project_id)
            meta = dict(entry.meta)
            if name is not None:
                meta["name"] = self._check_name(name, project_id)
            if archived is not None:
                in_use = sum(1 for e in self._projects.values() if not e.meta["archived"])
                if archived and not meta["archived"] and in_use <= 1:
                    raise ProjectError(422, "This is the only project in use, so it can't be archived.")
                meta["archived"] = archived
            if members is not None:
                meta["members"] = self._members(members)
            entry.store.save_project_meta(meta)
            entry.meta = meta
            return self._view(entry)


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
