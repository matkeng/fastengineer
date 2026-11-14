# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""The change log: who changed which record, when, and what changed.

Every write in ``storage`` calls :func:`log` inside its own transaction, so a
change and its log entry are saved (or rolled back) together. A record's
*version* is the id of its newest log entry; the API hands it out as an ETag
and refuses a save made against an older one (:class:`Conflict`).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from . import identity

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    user TEXT NOT NULL,
    machine TEXT NOT NULL,
    entity TEXT NOT NULL,
    record_id TEXT NOT NULL,
    parent_id TEXT,
    action TEXT NOT NULL,       -- create | update | delete
    label TEXT NOT NULL,        -- the record's name at the time, so the log reads well after a delete
    changes TEXT NOT NULL       -- JSON list of {path, old, new}
);
CREATE INDEX IF NOT EXISTS audit_record ON audit_log(entity, record_id, id);
CREATE INDEX IF NOT EXISTS audit_parent ON audit_log(parent_id, id);
"""

#: What each entity is called in messages and in the history view.
ENTITIES = {
    "mel_recipe": "MEL import",
    "mel_revision": "MEL file revision",
    "ref_enum": "list",
    "ref_tree": "tree",
    "ref_table": "table",
    "ref_row": "table row",
    "plant_areas": "plant areas list",
    "equipment_packages": "equipment packages list",
    "load_types": "load types list",
    "load_list": "load list",
    "eel": "electrical equipment list",
    "plc": "PLC list",
    "distribution_panels": "distribution panels list",
    "cable_routing": "cable routing map",
    "instrument_runsheet": "instrument runsheet",
    "enums": "enums",
    "master_columns": "master list columns",
    "load_fields": "load list fields",
    "load_summary": "load list summary page",
    "drawing_list": "drawing list",
    "document_list": "document list",
    "deliverable": "deliverable",
    "deliverable_revision": "deliverable revision",
    "cable_types": "cable types list",
    "motors": "motor data list",
    "drives": "drive data list",
    "starters": "starter coordination list",
    "load_factors": "load factors list",
    "instrument_types": "instrument types list",
    "pid_loops": "PID symbols loop",
    "equipment_codes": "equipment codes list",
    "instrument_codes": "instrument codes list",
    "load_list_row": "load list row",
    "sym_library": "symbol library",
    "sym_drawing": "drawing",
    "sym_template": "symbol template",
    "sym_override": "page override",
    "sym_review": "page review",
    "sym_run": "detection run",
    "generator": "generator",
    "gen_tables": "generator lookup tables",
    "gen_build": "build",
    "gen_hardware": "PLC hardware register",
    "gen_catalogue": "card and rack types",
    "project": "project",
}

MAX_CHANGES = 200   # per log entry; the rest is counted, not stored
MAX_VALUE = 2000    # characters of JSON kept for one old/new value
_IGNORED = {"updated_at"}  # bookkeeping fields that change on every save


class Conflict(Exception):
    """Someone else changed the record after this client last read it."""

    def __init__(self, entity: str, changed_by: str, changed_at: str):
        what = ENTITIES.get(entity, "record")
        super().__init__(f"This {what} was changed by {changed_by or 'someone else'} after you opened it. "
                         "Open it again to see their changes, then make yours again.")
        self.entity, self.changed_by, self.changed_at = entity, changed_by, changed_at


# -- differences ----------------------------------------------------------------

def _clip(value):
    text = json.dumps(value, ensure_ascii=False, default=str)
    if len(text) <= MAX_VALUE:
        return value
    return text[:MAX_VALUE] + f"… ({len(text)} characters)"


def _keyed(items: list) -> bool:
    return bool(items) and all(isinstance(i, dict) and isinstance(i.get("id"), str) for i in items) \
        and len({i["id"] for i in items}) == len(items)


def _item_name(item: dict) -> str:
    for key in ("name", "code", "label", "title", "tag", "number"):
        if isinstance(item.get(key), str) and item[key]:
            return item[key]
    return item["id"]


def _walk(old, new, path: str, out: list[dict]) -> None:
    if old == new:
        return
    if isinstance(old, dict) and isinstance(new, dict):
        for key in [*old, *(k for k in new if k not in old)]:
            if key in _IGNORED:
                continue
            _walk(old.get(key), new.get(key), f"{path}.{key}" if path else str(key), out)
        return
    if isinstance(old, list) and isinstance(new, list):
        if (_keyed(old) or not old) and (_keyed(new) or not new) and (old or new):
            before, after = {i["id"]: i for i in old}, {i["id"]: i for i in new}
            for key, item in before.items():
                here = f"{path}[{_item_name(item)}]"
                if key in after:
                    _walk(item, after[key], here, out)
                else:
                    out.append({"path": here, "old": item, "new": None})
            for key, item in after.items():
                if key not in before:
                    out.append({"path": f"{path}[{_item_name(item)}]", "old": None, "new": item})
            if [k for k in before if k in after] != [k for k in after if k in before]:
                out.append({"path": f"{path} (order)", "old": [_item_name(before[k]) for k in before],
                            "new": [_item_name(after[k]) for k in after]})
            return
        if len(old) == len(new):
            for i, (a, b) in enumerate(zip(old, new)):
                _walk(a, b, f"{path}[{i + 1}]", out)
            return
    out.append({"path": path, "old": old, "new": new})


def diff(old, new) -> list[dict]:
    """Field-level differences between two JSON values, as ``{path, old, new}``."""
    out: list[dict] = []
    _walk(old, new, "", out)
    return out


def _load(value):
    return json.loads(value) if isinstance(value, (str, bytes)) else value


def _label(*values) -> str:
    for v in values:
        if isinstance(v, dict):
            for key in ("name", "file_name", "title", "desc", "description"):
                if isinstance(v.get(key), str) and v[key]:
                    return v[key][:200]
    return ""


# -- writing --------------------------------------------------------------------

def _latest(db: sqlite3.Connection, entity: str, record_id: str):
    return db.execute("SELECT id, user, machine, at FROM audit_log WHERE entity = ? AND record_id = ? "
                      "ORDER BY id DESC LIMIT 1", (entity, record_id)).fetchone()


def version_of(db: sqlite3.Connection, entity: str, record_id: str) -> int:
    row = _latest(db, entity, record_id)
    return row[0] if row else 0


def check(db: sqlite3.Connection, entity: str, record_id: str, stored_time: str | None = None) -> None:
    """Raise :class:`Conflict` if the record moved on since the client read it.

    Call inside the write transaction. The client's own earlier changes (same user
    on the same machine) never conflict: its copy may be stale only because another
    of its own requests touched the record.
    """
    ctx = identity.current()
    latest = _latest(db, entity, record_id)
    stale = False
    if ctx.expect and ctx.expect[:2] == (entity, record_id):
        stale = (latest[0] if latest else 0) != ctx.expect[2]
    elif stored_time is not None and ctx.base_time:
        stale = _same_instant(stored_time, ctx.base_time) is False
    if not stale:
        return
    if latest and (latest[1], latest[2]) == (ctx.user, ctx.machine):
        return
    raise Conflict(entity, latest[1] if latest else "", latest[3] if latest else "")


def _same_instant(a: str, b: str) -> bool | None:
    try:
        return datetime.fromisoformat(a.replace("Z", "+00:00")) == datetime.fromisoformat(b.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None  # can't compare: don't block the save


def log(db: sqlite3.Connection, entity: str, record_id: str, before=None, after=None, *,
        parent_id: str | None = None, label: str = "", note: str | None = None,
        stored_time: str | None = None) -> None:
    """Record one change. ``before``/``after`` are the record's JSON (text or parsed);
    None for "did not exist". Updates that change nothing are not logged.

    Raises :class:`Conflict` (rolling the caller's transaction back) when the client
    saved over a version it had not seen.
    """
    old, new = _load(before), _load(after)
    action = "create" if old is None else "delete" if new is None else "update"
    if action != "create":
        check(db, entity, record_id, stored_time)
    if action == "update":
        changes = diff(old, new)
    elif action == "create":
        changes = [{"path": "", "old": None, "new": new}]
    else:
        changes = [{"path": "", "old": old, "new": None}]
    if not changes and not note:
        return
    extra = len(changes) - MAX_CHANGES
    changes = [{"path": c["path"], "old": _clip(c["old"]), "new": _clip(c["new"])} for c in changes[:MAX_CHANGES]]
    if extra > 0:
        changes.append({"path": "(more)", "old": None, "new": f"{extra} more changes not listed"})
    if note:  # after the cut-off, so a long change keeps its note
        changes.append({"path": "(note)", "old": None, "new": note})
    ctx = identity.current()
    db.execute("INSERT INTO audit_log (at, user, machine, entity, record_id, parent_id, action, label, changes) "
               "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
               (datetime.now(timezone.utc).isoformat(), ctx.user, ctx.machine, entity, record_id, parent_id,
                action, label or _label(new, old), json.dumps(changes, ensure_ascii=False, default=str)))


def data_of(db: sqlite3.Connection, table: str, where: str, args: tuple, column: str = "data") -> str | None:
    """The stored JSON of one row, or None. (Table and column names are constants in storage.)"""
    row = db.execute(f"SELECT {column} FROM {table} WHERE {where}", args).fetchone()
    return row[0] if row else None


# -- reading --------------------------------------------------------------------

def entries(db: sqlite3.Connection, *, entity: str | None = None, record_id: str | None = None,
            user: str | None = None, since: str | None = None, until: str | None = None,
            include_children: bool = False, limit: int = 100, before_id: int | None = None) -> list[dict]:
    where, args = [], []
    if entity and record_id and include_children:
        where.append("((entity = ? AND record_id = ?) OR parent_id = ?)")
        args += [entity, record_id, record_id]
    else:
        if entity:
            where.append("entity = ?")
            args.append(entity)
        if record_id:
            where.append("record_id = ?")
            args.append(record_id)
    if user:
        where.append("user LIKE ? ESCAPE '\\'")
        args.append("%" + user.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
    if since:
        where.append("at >= ?")
        args.append(since)
    if until:
        where.append("at <= ?")
        args.append(until)
    if before_id:
        where.append("id < ?")
        args.append(before_id)
    sql = "SELECT id, at, user, machine, entity, record_id, parent_id, action, label, changes FROM audit_log"
    if where:
        sql += " WHERE " + " AND ".join(where)
    rows = db.execute(sql + " ORDER BY id DESC LIMIT ?", (*args, max(1, min(limit, 1000)))).fetchall()
    return [{"id": i, "at": at, "user": u, "machine": m, "entity": e, "entity_label": ENTITIES.get(e, e),
             "record_id": r, "parent_id": p, "action": a, "label": lab, "changes": json.loads(ch)}
            for i, at, u, m, e, r, p, a, lab, ch in rows]


def users(db: sqlite3.Connection) -> list[str]:
    return [r[0] for r in db.execute("SELECT DISTINCT user FROM audit_log ORDER BY user")]
