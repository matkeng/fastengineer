# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""The Drawing List: the project's register of drawings.

A drawing has a number (required, unique), the project's name, up to three title lines, a
discipline, a type, a revision, a status, an issue date, the vendor's drawing number and
reference, the equipment it is about, and a scope.

Discipline, type and status are fixed choices: each is blank or an item of the project's
Enums (see keylists.enums), typed or imported as the item's code or name and kept by its id,
so renaming an item changes nothing here. The equipment reference is free: one or more tags
separated by commas, and a tag that is in neither the MEL nor the Electrical Equipment List
is only warned about.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from pydantic import BaseModel, Field

from ..refdata.models import RefValidationError, new_id
from ..refdata.validate import name_key
from .enums import ProjectEnums, lookup

#: (field, heading) of what is typed, in the list's column order.
COLUMNS: list[tuple[str, str]] = [
    ("number", "Drawing number"), ("project_name", "Project name"), ("title_1", "Title 1"), ("title_2", "Title 2"),
    ("title_3", "Title 3"), ("discipline", "Drawing discipline"), ("drawing_type", "Drawing type"), ("revision", "Revision"),
    ("status", "Status"), ("issue_date", "Issue date"), ("vendor_drg_number", "Vendor drg number"),
    ("vendor_reference", "Vendor reference"), ("equipment_reference", "Equipment reference"), ("scope", "Scope")]
FIELDS: list[str] = [c[0] for c in COLUMNS]
HEADINGS: list[str] = [c[1] for c in COLUMNS]
#: field -> (the enum it picks from, what it is called)
CHOICES: dict[str, tuple[str, str]] = {"discipline": ("disciplines", "discipline"), "drawing_type": ("drawing_types", "drawing type"),
                                       "status": ("drawing_statuses", "status")}
_TEXT = ("number", "project_name", "title_1", "title_2", "title_3", "revision", "vendor_drg_number", "vendor_reference", "scope")


class Drawing(BaseModel):
    id: str = Field(default_factory=new_id)
    number: str
    project_name: str = ""
    title_1: str = ""
    title_2: str = ""
    title_3: str = ""
    discipline_id: str | None = None  # an item of the Disciplines enum
    drawing_type_id: str | None = None  # an item of the Drawing types enum
    revision: str = ""
    status_id: str | None = None  # an item of the Drawing statuses enum
    issue_date: date | None = None
    vendor_drg_number: str = ""
    vendor_reference: str = ""
    equipment_reference: str = ""  # tags, separated by commas
    scope: str = ""


class DrawingList(BaseModel):
    items: list[Drawing] = Field(default_factory=list)
    updated_at: datetime | None = None


def _text(v: object) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return str(v).strip()


def parse_date(v: object) -> date | None:
    """A date as typed, pasted or read from a workbook: dd/mm/yyyy (or with - or .), yyyy-mm-dd,
    or Excel's number of days. Blank is None; anything else raises ValueError."""
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    text = _text(v)
    if not text:
        return None
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:[T ].*)?", text)
    if m:
        return date(int(m[1]), int(m[2]), int(m[3]))
    m = re.fullmatch(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2}|\d{4})", text)
    if m:
        year = int(m[3]) + (2000 if len(m[3]) == 2 else 0)
        return date(year, int(m[2]), int(m[1]))
    if re.fullmatch(r"\d{4,6}(\.\d+)?", text):  # Excel's day number
        return date(1899, 12, 30) + timedelta(days=int(float(text)))
    raise ValueError("Not a date: use dd/mm/yyyy")


def tags_of(reference: str) -> list[str]:
    """The tags of an equipment reference, as written (commas, semicolons or new lines between them)."""
    return [t.strip() for t in re.split(r"[,;\n]+", reference) if t.strip()]


def equipment_warnings(reference: str, known: set[str]) -> list[str]:
    """The tags of a reference that are not known. `known`: name_key of every tag in the MEL
    and the Electrical Equipment List."""
    return [t for t in tags_of(reference) if name_key(t) not in known]


def check_drawings(rows: list[dict], enums: ProjectEnums) -> DrawingList:
    """Check the drawings as they are typed or imported (`rows`: field -> value, see FIELDS; a
    choice as its code or name, or already as `<field>_id`). The number is required and unique;
    a choice is blank or an item of its enum; the date is a date. Raises RefValidationError
    with `<drawing id>.<field>` -> message. Order is kept."""
    errors: dict[str, str] = {}
    found = {field: lookup(getattr(enums, enum)) for field, (enum, _) in CHOICES.items()}
    ids = {field: {i.id for i in getattr(enums, enum)} for field, (enum, _) in CHOICES.items()}
    out: list[Drawing] = []
    seen_ids: set[str] = set()
    numbers: set[str] = set()
    for raw in rows:
        rid = str(raw.get("id") or new_id())
        if rid in seen_ids:
            raise RefValidationError("Two drawings have the same id.", {f"{rid}.number": "Duplicate item"})
        seen_ids.add(rid)
        data: dict[str, object] = {"id": rid} | {f: _text(raw.get(f)) for f in _TEXT}
        data["equipment_reference"] = ", ".join(tags_of(_text(raw.get("equipment_reference"))))
        if not data["number"]:
            errors[f"{rid}.number"] = "Drawing number is required"
        elif name_key(str(data["number"])) in numbers:
            errors[f"{rid}.number"] = f"Drawing number '{data['number']}' is used twice"
        numbers.add(name_key(str(data["number"])))
        for field, (_enum, what) in CHOICES.items():
            by_id = raw.get(f"{field}_id")
            text = _text(raw.get(field))
            if by_id and by_id in ids[field] and not text:
                data[f"{field}_id"] = by_id
            elif text:
                data[f"{field}_id"] = found[field].get(name_key(text))
                if data[f"{field}_id"] is None:
                    errors[f"{rid}.{field}"] = f"'{text}' is not a {what} of the project's Enums"
            elif by_id:
                errors[f"{rid}.{field}"] = f"That {what} is no longer in the project's Enums"
        try:
            data["issue_date"] = parse_date(raw.get("issue_date"))
        except ValueError as exc:
            errors[f"{rid}.issue_date"] = str(exc)
        out.append(Drawing.model_validate(data))
    if errors:
        raise RefValidationError(f"{len(errors)} problem(s) in the Drawing List.", errors)
    return DrawingList(items=out)


def as_typed(drawing: Drawing, enums: ProjectEnums) -> dict[str, str]:
    """A drawing as text, field -> value: its choices as the items' labels, its date as dd/mm/yyyy."""
    labels = {field: {i.id: i.label() for i in getattr(enums, enum)} for field, (enum, _) in CHOICES.items()}
    out = {f: getattr(drawing, f) for f in _TEXT} | {"equipment_reference": drawing.equipment_reference}
    for field in CHOICES:
        out[field] = labels[field].get(getattr(drawing, f"{field}_id") or "", "")
    out["issue_date"] = drawing.issue_date.strftime("%d/%m/%Y") if drawing.issue_date else ""
    return out
