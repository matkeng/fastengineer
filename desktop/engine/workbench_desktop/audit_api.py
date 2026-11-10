# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""The change log: who changed which record, when, and what changed (read-only)."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from .audit import ENTITIES
from .storage import get_store

router = APIRouter(prefix="/api/audit", tags=["change log"])


class Change(BaseModel):
    path: str            # e.g. "items[HV].description"; "" for the whole record
    old: object | None
    new: object | None


class AuditEntry(BaseModel):
    id: int
    at: datetime
    user: str
    machine: str
    entity: str
    entity_label: str    # e.g. "table row"
    record_id: str
    parent_id: str | None
    action: str          # create | update | delete
    label: str           # the record's name at the time
    changes: list[Change]


class AuditPage(BaseModel):
    entries: list[AuditEntry]
    more: bool           # older entries exist; ask again with before_id = the last id


def _utc(value: str | None, what: str) -> str | None:
    """Log times are stored as UTC ISO text, so filters are converted to the same form."""
    if not value:
        return None
    try:
        t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(400, f"'{what}' is not a date and time.") from exc
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t.astimezone(timezone.utc).isoformat()


@router.get("", response_model=AuditPage)
def list_entries(entity: str | None = None, record_id: str | None = None, user: str | None = None,
                 since: str | None = None, until: str | None = None,
                 children: bool = Query(False, description="with entity and record_id: include the record's "
                                                           "parts, e.g. a table's rows"),
                 limit: int = Query(100, ge=1, le=500), before_id: int | None = None) -> AuditPage:
    """Newest first."""
    rows = get_store().audit_entries(entity=entity, record_id=record_id, user=user, since=_utc(since, "since"),
                                     until=_utc(until, "until"), include_children=children, limit=limit + 1,
                                     before_id=before_id)
    return AuditPage(entries=rows[:limit], more=len(rows) > limit)


class AuditFilters(BaseModel):
    users: list[str]
    entities: dict[str, str]


@router.get("/filters", response_model=AuditFilters)
def filters() -> AuditFilters:
    """What the change log page offers in its filter boxes."""
    return AuditFilters(users=get_store().audit_users(), entities=ENTITIES)
