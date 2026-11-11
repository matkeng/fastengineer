# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""The project's Enums (the choice lists other lists pick from), its Drawing List and its
Document List (see workbench_core.keylists.enums and drawing_list). The two lists are the same
kind of register, so their routes are made by one function."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from workbench_core.keylists.drawing_list import DOCUMENTS, DRAWINGS, RegisterSpec, as_typed, check_drawings, equipment_warnings
from workbench_core.keylists.enums import ENUMS, EnumItem, ProjectEnums, check_enums
from workbench_core.refdata import RefValidationError, name_key

from .loadlist_api import mel_tags
from .refdata_api import invalid
from .storage import get_keylists

enums_router = APIRouter(prefix="/api/enums", tags=["enums"])
router = APIRouter(prefix="/api/drawing-list", tags=["drawing list"])
document_router = APIRouter(prefix="/api/document-list", tags=["document list"])


# -- enums ---------------------------------------------------------------------------------------

class EnumsView(BaseModel):
    enums: ProjectEnums
    titles: dict[str, str]  # enum key -> what it is called
    need_code: list[str]  # the enums whose items must have a code
    in_use: dict[str, int]  # item id -> how many drawings, documents or equipment codes use it


def _uses() -> dict[str, int]:
    """Enum item id -> how many drawings and documents (and, for a discipline, equipment codes) use it."""
    lists = get_keylists()
    enums = lists.enums()
    counts: dict[str, int] = {}
    for item_ids in ([(d.discipline_id, d.drawing_type_id, d.status_id) for d in lists.drawing_list().items]
                     + [(d.discipline_id, d.document_type_id, d.status_id) for d in lists.document_list().items]):
        for item_id in item_ids:
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
                                          + ". Change the drawings, documents or equipment codes that use them first."))
    coded = {code for c in lists.code_list("equipment-codes").items for code in c.disciplines}
    errors = {f"{d.id}.code": f"Equipment codes use the discipline {d.code}: its code can't change"
              for d in old.disciplines if d.code in coded and d.id in kept and kept[d.id].code != d.code}
    if errors:
        return invalid(RefValidationError(f"{len(errors)} discipline code(s) are in use and can't change.", errors))
    return _enums_view(lists.save_enums(enums))


# -- the Drawing List and the Document List --------------------------------------------------------

class Column(BaseModel):
    field: str
    heading: str


class RegisterView(BaseModel):
    """A register's items as text: each a dict of its fields (a choice as the item's label, the
    date as dd/mm/yyyy), with `<choice>_id` for each choice, and `unknown_equipment`: the tags of
    its equipment reference that are in neither the MEL nor the Electrical Equipment List."""
    name: str  # "Drawing List"
    item: str  # "drawing"
    items: list[dict]
    columns: list[Column]
    choices: dict[str, list[EnumItem]]  # field (discipline, drawing_type, status) -> the items it can be
    updated_at: str | None = None


def known_equipment() -> set[str]:
    """name_key of every tag in the MEL and the Electrical Equipment List."""
    return {name_key(t) for t in [i.tag for i in get_keylists().eel().items] + mel_tags() if name_key(t)}


def _stored(spec: RegisterSpec):
    lists = get_keylists()
    return lists.drawing_list() if spec is DRAWINGS else lists.document_list()


def view_of(spec: RegisterSpec, stored=None) -> RegisterView:
    stored = _stored(spec) if stored is None else stored
    enums = get_keylists().enums()
    known = known_equipment()
    items = [{"id": d.id} | as_typed(d, enums, spec) | {f"{f}_id": getattr(d, f"{f}_id") for f in spec.choices}
             | {"unknown_equipment": equipment_warnings(d.equipment_reference, known)} for d in stored.items]
    return RegisterView(name=spec.name, item=spec.item, items=items, columns=[Column(field=f, heading=h) for f, h in spec.columns],
                        choices={field: getattr(enums, enum) for field, (enum, _) in spec.choices.items()},
                        updated_at=stored.updated_at and stored.updated_at.isoformat())


def checked(rows: list[dict], spec: RegisterSpec = DRAWINGS):
    """The list to save; raises RefValidationError, each problem named by its drawing or document."""
    try:
        return check_drawings(rows, get_keylists().enums(), spec)
    except RefValidationError as exc:
        nameless = f"A {spec.item} with no number"
        names = {str(r.get("id")): str(r.get("number") or "").strip() or nameless for r in rows}
        first = [f"{names.get(f.split('.')[0], nameless)}: {m}" for f, m in list(exc.fields.items())[:5]]
        more = f" and {len(exc.fields) - 5} more" if len(exc.fields) > 5 else ""
        raise RefValidationError(f"{exc.message} {'; '.join(first)}{more}.", exc.fields) from exc


class RegisterBody(BaseModel):
    items: list[dict]  # as typed: check_drawings resolves the choices and the date, and names each problem


DrawingsBody = RegisterBody  # (the name the workbook import uses)


def save_register(spec: RegisterSpec, body: RegisterBody):
    lists = get_keylists()
    try:
        ok = checked(body.items, spec)
    except RefValidationError as exc:
        return invalid(exc)
    return view_of(spec, lists.save_drawing_list(ok) if spec is DRAWINGS else lists.save_document_list(ok))


@router.get("", response_model=RegisterView)
def get_drawings() -> RegisterView:
    return view_of(DRAWINGS)


@router.put("", response_model=RegisterView)
def save_drawings(body: RegisterBody):
    return save_register(DRAWINGS, body)


@document_router.get("", response_model=RegisterView)
def get_documents() -> RegisterView:
    return view_of(DOCUMENTS)


@document_router.put("", response_model=RegisterView)
def save_documents(body: RegisterBody):
    return save_register(DOCUMENTS, body)
