# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""The Instrument Runsheet: what the Instrument generator will run from.

One row is one instrument assembly: which equipment type it is (an Equipment Type of the
Equipment Packages list, whose predefined rows say what it adds to each deliverable list),
which plant area it is in, the equipment it belongs to, and the values those rows are filled
in with: a name suffix, the P&ID, the marshalling box its IO goes through, whether it is
confirmed, its PLC rack, and up to 35 numbers.

The three references must exist for the list to be saved: the equipment type by its name, the
area by its tag number, and the parent equipment by its tag in the Electrical Equipment List
or the MEL. The type and the area are kept by id, so renaming one changes nothing here; the
parent is kept as its tag. Rows may repeat (the same type on the same equipment twice, with
different numbers) and keep their order.

In an equipment type's rows, each column is a tag: <<STD>>, <<Area>>, <<MECH>>, <<SUF>>,
<<PID>>, <<VIA_MB>>, <<CONF>>, <<Rack>> and <<#1>> to <<#35>>.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from ..refdata.models import RefValidationError, new_id
from ..refdata.validate import name_key

NUMBERS = 35
#: (key, heading, tag, what the tag stands for), in the runsheet's column order.
COLUMNS: list[tuple[str, str, str, str]] = [
    ("equipment_type", "Equipment Type Ref", "<<STD>>", "the name of the row's equipment type"),
    ("area", "Area Ref", "<<Area>>", "the tag number of its plant area"),
    ("parent", "Parent Equipment Ref", "<<MECH>>", "the tag of the equipment it belongs to"),
    ("suffix", "Name Suffix", "<<SUF>>", "its name suffix"),
    ("pid", "PID", "<<PID>>", "its P&ID"),
    ("via_mb", "IO via MARSHALLING BOX", "<<VIA_MB>>", "the marshalling box its IO goes through"),
    ("confirmed", "Confirmed", "<<CONF>>", "TRUE or FALSE"),
    ("rack", "PLC Rack Num", "<<Rack>>", "its PLC rack number"),
] + [(str(n), f"#{n}", f"<<#{n}>>", f"its number {n}") for n in range(1, NUMBERS + 1)]
KEYS: list[str] = [c[0] for c in COLUMNS]
HEADINGS: list[str] = [c[1] for c in COLUMNS]
#: The tags an equipment type's rows can use: (tag, what it stands for).
TAGS: list[tuple[str, str]] = [(c[2], c[3]) for c in COLUMNS]
_TRUE = ("true", "yes", "y", "1", "x")
_FALSE = ("false", "no", "n", "0", "")


class RunsheetRow(BaseModel):
    id: str = Field(default_factory=new_id)
    equipment_type_id: str
    plant_area_id: str
    parent_tag: str
    suffix: str = ""
    pid: str = ""
    via_mb: str = ""
    confirmed: bool = False
    rack: str = ""
    numbers: list[str] = Field(default_factory=lambda: [""] * NUMBERS)  # "#1".."#35", as typed


class InstrumentRunsheet(BaseModel):
    rows: list[RunsheetRow] = Field(default_factory=list)
    updated_at: datetime | None = None


class TypedRow(BaseModel):
    """A row as it is typed, pasted or read from a workbook: one text per column (see KEYS)."""
    id: str = Field(default_factory=new_id)
    cells: list[str | int | float | bool | None] = Field(default_factory=list)  # a number or TRUE/FALSE is read as its text


def _text(v: object) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return str(v).strip()


def index(pairs: list[tuple[str, str]]) -> dict[str, str]:
    """(id, name) pairs -> name_key(name) -> id (the first of two with the same name)."""
    out: dict[str, str] = {}
    for item_id, name in pairs:
        if name_key(name):
            out.setdefault(name_key(name), item_id)
    return out


def problems(rows: list[TypedRow], types: dict[str, str], areas: dict[str, str], parents: dict[str, str]) -> tuple[
        list[RunsheetRow], dict[str, str]]:
    """The rows as they would be saved, and what stops them: `<row id>.<column key>` -> message.
    `types`: name_key(equipment type name) -> id; `areas`: name_key(plant area tag) -> id;
    `parents`: name_key(tag) -> the tag as it is written in the Electrical Equipment List or
    the MEL. A row with nothing in it is dropped."""
    errors: dict[str, str] = {}
    out: list[RunsheetRow] = []
    ids: set[str] = set()
    for raw in rows:
        cells = [_text(c) for c in raw.cells[:len(KEYS)]] + [""] * (len(KEYS) - len(raw.cells))
        v = dict(zip(KEYS, cells))
        if not any(text for key, text in v.items() if key != "confirmed"):  # a blank row (its Confirmed alone is nothing)
            continue
        rid = raw.id if raw.id and raw.id not in ids else new_id()
        ids.add(rid)
        found = {}
        for key, label, known, where in (("equipment_type", "Equipment Type Ref", types, "an equipment type of Equipment Packages"),
                                         ("area", "Area Ref", areas, "a plant area's tag number"),
                                         ("parent", "Parent Equipment Ref", parents,
                                          "a tag in the Electrical Equipment List or the MEL")):
            found[key] = known.get(name_key(v[key]))
            if not v[key]:
                errors[f"{rid}.{key}"] = f"{label} is required"
            elif found[key] is None:
                errors[f"{rid}.{key}"] = f"'{v[key]}' is not {where}"
        flag = v["confirmed"].casefold()
        if flag not in _TRUE and flag not in _FALSE:
            errors[f"{rid}.confirmed"] = "Confirmed is TRUE or FALSE"
        out.append(RunsheetRow(
            id=rid, equipment_type_id=found["equipment_type"] or "", plant_area_id=found["area"] or "",
            parent_tag=found["parent"] or v["parent"], suffix=v["suffix"], pid=v["pid"], via_mb=v["via_mb"],
            confirmed=flag in _TRUE, rack=v["rack"], numbers=[v[str(n)] for n in range(1, NUMBERS + 1)]))
    return out, errors


def check_runsheet(rows: list[TypedRow], types: dict[str, str], areas: dict[str, str], parents: dict[str, str]) -> InstrumentRunsheet:
    """The runsheet to save; raises RefValidationError if any row has a problem (see problems)."""
    out, errors = problems(rows, types, areas, parents)
    if errors:
        raise RefValidationError(f"{len(errors)} problem(s) in the Instrument Runsheet.", errors)
    return InstrumentRunsheet(rows=out)


def as_typed(runsheet: InstrumentRunsheet, type_names: dict[str, str], area_tags: dict[str, str]) -> list[TypedRow]:
    """The saved rows as text, one per column. `type_names`: equipment type id -> name;
    `area_tags`: plant area id -> tag number. (A type or area that is gone shows blank: it then
    has to be chosen again before the list can be saved.)"""
    return [TypedRow(id=r.id, cells=[
        type_names.get(r.equipment_type_id, ""), area_tags.get(r.plant_area_id, ""), r.parent_tag, r.suffix, r.pid, r.via_mb,
        "TRUE" if r.confirmed else "FALSE", r.rack, *(r.numbers + [""] * NUMBERS)[:NUMBERS]]) for r in runsheet.rows]


def row_label(row: TypedRow, number: int) -> str:
    """How a row is named in a message: its number, with its type and parent when it has them."""
    cells = row.cells + [""] * 3
    what = " / ".join(c for c in (cells[0], cells[2]) if c)
    return f"Row {number}" + (f" ({what})" if what else "")
