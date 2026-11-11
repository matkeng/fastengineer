# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""The project's Enums (the choice lists other lists pick from) and its Drawing List (see
workbench_core.keylists.enums and drawing_list)."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from workbench_core.keylists.drawing_list import CHOICES, COLUMNS, DrawingList, as_typed, check_drawings, equipment_warnings
from workbench_core.keylists.enums import ENUMS, EnumItem, ProjectEnums, check_enums
from workbench_core.refdata import RefValidationError, name_key

from .loadlist_api import mel_tags
from .refdata_api import invalid
from .storage import get_keylists

enums_router = APIRouter(prefix="/api/enums", tags=["enums"])
router = APIRouter(prefix="/api/drawing-list", tags=["drawing list"])


# -- enums ---------------------------------------------------------------------------------------

class EnumsView(BaseModel):
    enums: ProjectEnums
    titles: dict[str, str]  # enum key -> what it is called
    need_code: list[str]  # the enums whose items must have a code
    in_use: dict[str, int]  # item id -> how many drawings or equipment codes use it


def _uses() -> dict[str, int]:
    """Enum item id -> how many drawings (and, for a discipline, equipment codes) use it."""
    lists = get_keylists()
    enums = lists.enums()
    counts: dict[str, int] = {}
    for d in lists.drawing_list().items:
        for item_id in (d.discipline_id, d.drawing_type_id, d.status_id):
            if item_id:
                counts[item_id] = counts.get(item_id, 0) + 1
    by_code = {d.code: d.id for d in enums.disciplines}
    for c in lists.code_list("equipment-codes").items:
        for code in c.disciplines:
            if code in by_code:
                counts[by_code[code]] = counts.get(by_code[code], 0) + 1
    return counts


def _enums_view(enums: ProjectEnums) -> EnumsView:
    return EnumsView(enums=enums, titles={k: v[0] for k, v in ENUMS.items()}, need_code=[k for k, v in ENUMS.items() if v[2]],
                     in_use=_uses())


@enums_router.get("", response_model=EnumsView)
def get_enums() -> EnumsView:
    return _enums_view(get_keylists().enums())


@enums_router.put("", response_model=EnumsView)
def save_enums(body: ProjectEnums):
    """Save the three enums. An item that drawings or equipment codes use can't be removed, and a
    discipline that equipment codes use keeps its code (they refer to it by code)."""
    lists = get_keylists()
    try:
        enums = check_enums(body)
    except RefValidationError as exc:
        return invalid(exc)
    old = lists.enums()
    uses = _uses()
    kept = {i.id: i for k in ENUMS for i in getattr(enums, k)}
    gone = [f"{i.label()} ({uses[i.id]} use{'s' if uses[i.id] > 1 else ''})"
            for k in ENUMS for i in getattr(old, k) if i.id not in kept and uses.get(i.id)]
    if gone:
        return invalid(RefValidationError("These items are in use and can't be removed: " + ", ".join(gone)
                                          + ". Change the drawings or equipment codes that use them first."))
    coded = {code for c in lists.code_list("equipment-codes").items for code in c.disciplines}
    errors = {f"{d.id}.code": f"Equipment codes use the discipline {d.code}: its code can't change"
              for d in old.disciplines if d.code in coded and d.id in kept and kept[d.id].code != d.code}
    if errors:
        return invalid(RefValidationError(f"{len(errors)} discipline code(s) are in use and can't change.", errors))
    return _enums_view(lists.save_enums(enums))


# -- the Drawing List -----------------------------------------------------------------------------

class DrawingRow(BaseModel):
    """A drawing as text: its choices as the items' labels (and ids), its date as dd/mm/yyyy."""
    id: str
    number: str = ""
    project_name: str = ""
    title_1: str = ""
    title_2: str = ""
    title_3: str = ""
    discipline: str = ""
    discipline_id: str | None = None
    drawing_type: str = ""
    drawing_type_id: str | None = None
    revision: str = ""
    status: str = ""
    status_id: str | None = None
    issue_date: str = ""
    vendor_drg_number: str = ""
    vendor_reference: str = ""
    equipment_reference: str = ""
    scope: str = ""
    unknown_equipment: list[str] = []  # tags of its equipment reference that are in neither the MEL nor the EEL


class Column(BaseModel):
    field: str
    heading: str


class DrawingsView(BaseModel):
    items: list[DrawingRow]
    columns: list[Column]
    choices: dict[str, list[EnumItem]]  # field (discipline, drawing_type, status) -> the items it can be
    updated_at: str | None = None


def known_equipment() -> set[str]:
    """name_key of every tag in the MEL and the Electrical Equipment List."""
    return {name_key(t) for t in [i.tag for i in get_keylists().eel().items] + mel_tags() if name_key(t)}


def _view(drawings: DrawingList) -> DrawingsView:
    enums = get_keylists().enums()
    known = known_equipment()
    items = [DrawingRow(id=d.id, **as_typed(d, enums), discipline_id=d.discipline_id, drawing_type_id=d.drawing_type_id,
                        status_id=d.status_id, unknown_equipment=equipment_warnings(d.equipment_reference, known))
             for d in drawings.items]
    return DrawingsView(items=items, columns=[Column(field=f, heading=h) for f, h in COLUMNS],
                        choices={field: getattr(enums, enum) for field, (enum, _) in CHOICES.items()},
                        updated_at=drawings.updated_at and drawings.updated_at.isoformat())


def checked(rows: list[dict]) -> DrawingList:
    """The list to save; raises RefValidationError, each problem named by its drawing."""
    try:
        return check_drawings(rows, get_keylists().enums())
    except RefValidationError as exc:
        names = {str(r.get("id")): str(r.get("number") or "").strip() or "A drawing with no number" for r in rows}
        first = [f"{names.get(f.split('.')[0], 'A drawing')}: {m}" for f, m in list(exc.fields.items())[:5]]
        more = f" and {len(exc.fields) - 5} more" if len(exc.fields) > 5 else ""
        raise RefValidationError(f"{exc.message} {'; '.join(first)}{more}.", exc.fields) from exc


@router.get("", response_model=DrawingsView)
def get_drawings() -> DrawingsView:
    return _view(get_keylists().drawing_list())


class DrawingsBody(BaseModel):
    items: list[dict]  # as typed: check_drawings resolves the choices and the date, and names each problem


@router.put("", response_model=DrawingsView)
def save_drawings(body: DrawingsBody):
    try:
        return _view(get_keylists().save_drawing_list(checked(body.items)))
    except RefValidationError as exc:
        return invalid(exc)
