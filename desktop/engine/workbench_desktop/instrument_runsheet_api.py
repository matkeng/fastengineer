# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""The Instrument Runsheet: what the Instrument generator will run from (see
workbench_core.keylists.instrument_runsheet). Its rows are typed and pasted as text; a save
resolves each row's equipment type, plant area and parent equipment, and is refused unless
all three exist."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from workbench_core.keylists.instrument_runsheet import (MAX_NUMBERS, InstrumentRunsheet, TypedRow, as_typed, check_runsheet, columns,
                                                         index, number_count, problems, row_label)
from workbench_core.refdata import RefValidationError, name_key

from .loadlist_api import mel_tags
from .refdata_api import invalid
from .storage import get_keylists

router = APIRouter(prefix="/api/instrument-runsheet", tags=["instrument runsheet"])


class Column(BaseModel):
    key: str
    heading: str
    tag: str


class RunsheetView(BaseModel):
    rows: list[TypedRow]  # one text per column
    columns: list[Column]  # with as many number columns as the widest row uses (35 at least)
    max_numbers: int = MAX_NUMBERS  # the most number columns a runsheet can have
    equipment_types: list[str]  # the names an Equipment Type Ref can be
    areas: list[str]  # the tag numbers an Area Ref can be
    parents: list[str]  # the tags a Parent Equipment Ref can be (Electrical Equipment List and MEL)
    errors: dict[str, str]  # `<row id>.<column key>` -> message (saved rows whose references have gone)
    updated_at: str | None = None


class Known(BaseModel):
    types: list[tuple[str, str]]  # (id, name)
    areas: list[tuple[str, str]]  # (id, tag number)
    parents: list[str]


def known() -> Known:
    """What a row can refer to, as the project is now."""
    lists = get_keylists()
    parents: dict[str, str] = {}
    for tag in [i.tag for i in lists.eel().items] + mel_tags():
        if name_key(tag):
            parents.setdefault(name_key(tag), tag.strip())
    return Known(types=[(t.id, t.name) for t in lists.equipment_packages().types],
                 areas=[(n.id, n.tag) for n in lists.plant_areas().nodes], parents=list(parents.values()))


def checked(rows: list[TypedRow], k: Known | None = None) -> InstrumentRunsheet:
    """The runsheet to save; raises RefValidationError, each problem named by its row."""
    k = k or known()
    try:
        return check_runsheet(rows, index(k.types), index(k.areas), {name_key(p): p for p in k.parents})
    except RefValidationError as exc:
        kept = [r for r in rows if any(str(c or "").strip() for c in r.cells)]
        labels = {r.id: row_label(r, n) for n, r in enumerate(kept, start=1)}
        first = [f"{labels.get(f.split('.')[0], 'A row')}: {m}" for f, m in list(exc.fields.items())[:5]]
        more = f" and {len(exc.fields) - 5} more" if len(exc.fields) > 5 else ""
        raise RefValidationError(f"{exc.message} {'; '.join(first)}{more}.", exc.fields) from exc


def _view(sheet: InstrumentRunsheet) -> RunsheetView:
    k = known()
    rows = as_typed(sheet, dict(k.types), dict(k.areas))
    _, errors = problems(rows, index(k.types), index(k.areas), {name_key(p): p for p in k.parents})
    return RunsheetView(rows=rows, columns=[Column(key=c[0], heading=c[1], tag=c[2]) for c in columns(number_count(sheet))],
                        max_numbers=MAX_NUMBERS,
                        equipment_types=[n for _, n in k.types], areas=[t for _, t in k.areas], parents=k.parents, errors=errors,
                        updated_at=sheet.updated_at and sheet.updated_at.isoformat())


@router.get("", response_model=RunsheetView)
def get_runsheet() -> RunsheetView:
    return _view(get_keylists().instrument_runsheet())


class RunsheetBody(BaseModel):
    rows: list[TypedRow]


@router.put("", response_model=RunsheetView)
def save_runsheet(body: RunsheetBody):
    try:
        return _view(get_keylists().save_instrument_runsheet(checked(body.rows)))
    except RefValidationError as exc:
        return invalid(exc)
