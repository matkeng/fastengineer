# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""The Instrument Runsheet: what the Instrument generator will run from.

One row is one instrument assembly: which equipment type it is (an Equipment Type of the
Equipment Packages list, whose predefined rows say what it adds to each deliverable list),
which plant area it is in, the equipment it belongs to, and the values those rows are filled
in with: a name suffix, the P&ID, the marshalling box its IO goes through, whether it is
confirmed, its PLC rack, and its numbers: #1, #2, ... The runsheet shows 35 number columns to
start with and as many more as its widest row uses (up to MAX_NUMBERS).

The three references must exist for the list to be saved: the equipment type by its name, the
area by its tag number, and the parent equipment by its tag in the Electrical Equipment List
or the MEL. The type and the area are kept by id, so renaming one changes nothing here; the
parent is kept as its tag. Rows may repeat (the same type on the same equipment twice, with
different numbers) and keep their order.

In an equipment type's rows, each column is a tag: <<STD>>, <<Area>>, <<MECH>>, <<SUF>>,
<<PID>>, <<VIA_MB>>, <<CONF>>, <<Rack>> and <<#1>>, <<#2>>, ... for the numbers.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from ..refdata.models import RefValidationError, new_id
from ..refdata.validate import name_key

#: Number columns a runsheet always shows; a row can have more, and then every row shows that many.
NUMBERS = 35
MAX_NUMBERS = 500
#: (key, heading, tag, what the tag stands for) of the columns before the numbers.
FIXED: list[tuple[str, str, str, str]] = [
    ("equipment_type", "Equipment Type Ref", "<<STD>>", "the name of the row's equipment type"),
    ("area", "Area Ref", "<<Area>>", "the tag number of its plant area"),
    ("parent", "Parent Equipment Ref", "<<MECH>>", "the tag of the equipment it belongs to"),
    ("suffix", "Name Suffix", "<<SUF>>", "its name suffix"),
    ("pid", "PID", "<<PID>>", "its P&ID"),
    ("via_mb", "IO via MARSHALLING BOX", "<<VIA_MB>>", "the marshalling box its IO goes through"),
    ("confirmed", "Confirmed", "<<CONF>>", "TRUE or FALSE"),
    ("rack", "PLC Rack Num", "<<Rack>>", "its PLC rack number"),
]


def columns(numbers: int = NUMBERS) -> list[tuple[str, str, str, str]]:
    """The runsheet's columns, in order, with `numbers` number columns (at least NUMBERS)."""
    return FIXED + [(str(n), f"#{n}", f"<<#{n}>>", f"its number {n}") for n in range(1, max(numbers, NUMBERS) + 1)]


def headings(numbers: int = NUMBERS) -> list[str]:
    return [c[1] for c in columns(numbers)]


def tags(numbers: int = NUMBERS) -> list[tuple[str, str]]:
    """The tags an equipment type's rows can use: (tag, what it stands for)."""
    return [(c[2], c[3]) for c in columns(numbers)]


#: The columns, headings and tags of a runsheet with the usual 35 numbers.
COLUMNS = columns()
KEYS: list[str] = [c[0] for c in COLUMNS]
HEADINGS: list[str] = headings()
TAGS: list[tuple[str, str]] = tags()
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
    numbers: list[str] = Field(default_factory=list)  # "#1", "#2", ... as typed, up to the last one that has a value


class InstrumentRunsheet(BaseModel):
    rows: list[RunsheetRow] = Field(default_factory=list)
    updated_at: datetime | None = None


class TypedRow(BaseModel):
    """A row as it is typed, pasted or read from a workbook: one text per column (see columns();
    it may have more number cells than the usual 35, or fewer cells than there are columns)."""
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
        fixed = len(FIXED)
        cells = [_text(c) for c in raw.cells] + [""] * (fixed - len(raw.cells))
        v = dict(zip(KEYS, cells[:fixed]))
        numbers = cells[fixed:]
        while numbers and not numbers[-1]:  # kept up to the last number that has a value
            numbers.pop()
        v["numbers"] = "x" if numbers else ""  # (so a row with only numbers is not taken as blank)
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
            confirmed=flag in _TRUE, rack=v["rack"], numbers=numbers[:MAX_NUMBERS]))
        if len(numbers) > MAX_NUMBERS:
            errors[f"{rid}.{MAX_NUMBERS}"] = f"A row has at most {MAX_NUMBERS} numbers"
    return out, errors


def number_count(runsheet: InstrumentRunsheet) -> int:
    """How many number columns the runsheet shows: 35, or as many as its widest row uses."""
    return max([NUMBERS] + [len(r.numbers) for r in runsheet.rows])


def check_runsheet(rows: list[TypedRow], types: dict[str, str], areas: dict[str, str], parents: dict[str, str]) -> InstrumentRunsheet:
    """The runsheet to save; raises RefValidationError if any row has a problem (see problems)."""
    out, errors = problems(rows, types, areas, parents)
    if errors:
        raise RefValidationError(f"{len(errors)} problem(s) in the Instrument Runsheet.", errors)
    return InstrumentRunsheet(rows=out)


def as_typed(runsheet: InstrumentRunsheet, type_names: dict[str, str], area_tags: dict[str, str]) -> list[TypedRow]:
    """The saved rows as text, one per column, every row as wide as the widest (and at least
    the usual 35 numbers). `type_names`: equipment type id -> name;
    `area_tags`: plant area id -> tag number. (A type or area that is gone shows blank: it then
    has to be chosen again before the list can be saved.)"""
    n = number_count(runsheet)
    return [TypedRow(id=r.id, cells=[
        type_names.get(r.equipment_type_id, ""), area_tags.get(r.plant_area_id, ""), r.parent_tag, r.suffix, r.pid, r.via_mb,
        "TRUE" if r.confirmed else "FALSE", r.rack, *(r.numbers + [""] * n)[:n]]) for r in runsheet.rows]


def row_label(row: TypedRow, number: int) -> str:
    """How a row is named in a message: its number, with its type and parent when it has them."""
    cells = row.cells + [""] * 3
    what = " / ".join(c for c in (cells[0], cells[2]) if c)
    return f"Row {number}" + (f" ({what})" if what else "")
