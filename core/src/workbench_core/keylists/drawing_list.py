# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""The Drawing List: the project's register of drawings.

A drawing has a number (required, unique), the project's name, up to three title lines, a
discipline, a type, a revision, a status, an issue date, the vendor's drawing number and
reference, the equipment it is about, a scope, and a hyperlink to where the drawing is kept (a
web address, or the path of a file or folder).

The **Document List** is the same register for the project's documents (specifications,
datasheets, reports...): identical, but with one title line, and its type picked from the
Document types enum. Both are described by a RegisterSpec, and every function here takes one.

Discipline, type and status are fixed choices: each is blank or an item of the project's
Enums (see keylists.enums), typed or imported as the item's code or name and kept by its id,
so renaming an item changes nothing here. The equipment reference is free: one or more tags
separated by commas, and a tag that is in neither the MEL nor the Electrical Equipment List
is only warned about.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from dataclasses import dataclass

from pydantic import BaseModel, Field

from ..refdata.models import RefValidationError, new_id
from ..refdata.validate import name_key
from .enums import ProjectEnums, lookup

#: (field, heading) of what is typed, in the list's column order.
COLUMNS: list[tuple[str, str]] = [
    ("number", "Drawing number"), ("project_name", "Project name"), ("title_1", "Title 1"), ("title_2", "Title 2"),
    ("title_3", "Title 3"), ("discipline", "Drawing discipline"), ("drawing_type", "Drawing type"), ("revision", "Revision"),
    ("status", "Status"), ("issue_date", "Issue date"), ("vendor_drg_number", "Vendor drg number"),
    ("vendor_reference", "Vendor reference"), ("equipment_reference", "Equipment reference"), ("scope", "Scope"),
    ("hyperlink", "Hyperlink")]
FIELDS: list[str] = [c[0] for c in COLUMNS]
HEADINGS: list[str] = [c[1] for c in COLUMNS]
#: field -> (the enum it picks from, what it is called)
CHOICES: dict[str, tuple[str, str]] = {"discipline": ("disciplines", "discipline"), "drawing_type": ("drawing_types", "drawing type"),
                                       "status": ("drawing_statuses", "status")}
_TEXT = ("number", "project_name", "title_1", "title_2", "title_3", "revision", "vendor_drg_number", "vendor_reference", "scope",
         "hyperlink")
_SCHEME = re.compile(r"^([A-Za-z][A-Za-z0-9+.\-]*):")


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
    hyperlink: str = ""  # where the drawing is kept: http(s)://..., file://..., or a file or folder path


class DrawingList(BaseModel):
    items: list[Drawing] = Field(default_factory=list)
    updated_at: datetime | None = None


class Document(BaseModel):
    id: str = Field(default_factory=new_id)
    number: str
    project_name: str = ""
    title: str = ""
    discipline_id: str | None = None  # an item of the Disciplines enum
    document_type_id: str | None = None  # an item of the Document types enum
    revision: str = ""
    status_id: str | None = None  # an item of the Drawing statuses enum (drawings and documents share it)
    issue_date: date | None = None
    vendor_doc_number: str = ""
    vendor_reference: str = ""
    equipment_reference: str = ""
    scope: str = ""
    hyperlink: str = ""


class DocumentList(BaseModel):
    items: list[Document] = Field(default_factory=list)
    updated_at: datetime | None = None


@dataclass(frozen=True)
class RegisterSpec:
    """A register of numbered items (the Drawing List, the Document List)."""
    key: str  # the list's id, as in its URL
    name: str  # "Drawing List"
    item: str  # "drawing"
    columns: tuple[tuple[str, str], ...]  # (field, heading), in order; the first is the number
    choices: dict[str, tuple[str, str]]  # field -> (the enum it picks from, what it is called)
    model: type[BaseModel]
    list_model: type[BaseModel]

    @property
    def fields(self) -> list[str]:
        return [c[0] for c in self.columns]

    @property
    def headings(self) -> list[str]:
        return [c[1] for c in self.columns]

    @property
    def text(self) -> list[str]:
        """The fields kept as plain text."""
        return [f for f in self.fields if f not in self.choices and f not in ("issue_date", "equipment_reference")]


DRAWINGS = RegisterSpec("drawing-list", "Drawing List", "drawing", tuple(COLUMNS), CHOICES, Drawing, DrawingList)
DOCUMENTS = RegisterSpec(
    "document-list", "Document List", "document",
    (("number", "Document number"), ("project_name", "Project name"), ("title", "Title"), ("discipline", "Document discipline"),
     ("document_type", "Document type"), ("revision", "Revision"), ("status", "Status"), ("issue_date", "Issue date"),
     ("vendor_doc_number", "Vendor doc number"), ("vendor_reference", "Vendor reference"),
     ("equipment_reference", "Equipment reference"), ("scope", "Scope"), ("hyperlink", "Hyperlink")),
    {"discipline": ("disciplines", "discipline"), "document_type": ("document_types", "document type"),
     "status": ("drawing_statuses", "status")}, Document, DocumentList)
REGISTERS: dict[str, RegisterSpec] = {DRAWINGS.key: DRAWINGS, DOCUMENTS.key: DOCUMENTS}


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


def link_problem(link: str) -> str | None:
    """What is wrong with a hyperlink, if anything. A link is a web address (http or https), a
    file:// address, or the path of a file or folder (C:\\..., \\\\server\\share\\..., /...). Anything
    else that has a scheme (javascript:, data:, ...) is refused, so a link is safe to open."""
    m = _SCHEME.match(link)
    if not link or m is None or len(m[1]) == 1:  # blank, a path, or a drive letter
        return None
    if m[1].casefold() in ("http", "https"):
        return None if re.match(r"^https?://[^\s/]+", link, re.I) else "Not a web address: use https://..."
    if m[1].casefold() == "file":
        return None
    return "A link is a web address (https://...) or the path of a file or folder"


def tags_of(reference: str) -> list[str]:
    """The tags of an equipment reference, as written (commas, semicolons or new lines between them)."""
    return [t.strip() for t in re.split(r"[,;\n]+", reference) if t.strip()]


def equipment_warnings(reference: str, known: set[str]) -> list[str]:
    """The tags of a reference that are not known. `known`: name_key of every tag in the MEL
    and the Electrical Equipment List."""
    return [t for t in tags_of(reference) if name_key(t) not in known]


def check_drawings(rows: list[dict], enums: ProjectEnums, spec: RegisterSpec = DRAWINGS):
    """Check the drawings (or, with DOCUMENTS, the documents) as they are typed or imported
    (`rows`: field -> value, see the spec's fields; a
    choice as its code or name, or already as `<field>_id`). The number is required and unique;
    a choice is blank or an item of its enum; the date is a date. Raises RefValidationError
    with `<drawing id>.<field>` -> message. Order is kept."""
    errors: dict[str, str] = {}
    found = {field: lookup(getattr(enums, enum)) for field, (enum, _) in spec.choices.items()}
    ids = {field: {i.id for i in getattr(enums, enum)} for field, (enum, _) in spec.choices.items()}
    out: list = []
    seen_ids: set[str] = set()
    numbers: set[str] = set()
    for raw in rows:
        rid = str(raw.get("id") or new_id())
        if rid in seen_ids:
            raise RefValidationError(f"Two {spec.item}s have the same id.", {f"{rid}.number": "Duplicate item"})
        seen_ids.add(rid)
        data: dict[str, object] = {"id": rid} | {f: _text(raw.get(f)) for f in spec.text}
        data["equipment_reference"] = ", ".join(tags_of(_text(raw.get("equipment_reference"))))
        if not data["number"]:
            errors[f"{rid}.number"] = f"{spec.headings[0]} is required"
        elif name_key(str(data["number"])) in numbers:
            errors[f"{rid}.number"] = f"{spec.headings[0]} '{data['number']}' is used twice"
        numbers.add(name_key(str(data["number"])))
        for field, (_enum, what) in spec.choices.items():
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
        problem = link_problem(str(data["hyperlink"]))
        if problem:
            errors[f"{rid}.hyperlink"] = problem
        try:
            data["issue_date"] = parse_date(raw.get("issue_date"))
        except ValueError as exc:
            errors[f"{rid}.issue_date"] = str(exc)
        out.append(spec.model.model_validate(data))
    if errors:
        raise RefValidationError(f"{len(errors)} problem(s) in the {spec.name}.", errors)
    return spec.list_model(items=out)


def as_typed(drawing, enums: ProjectEnums, spec: RegisterSpec = DRAWINGS) -> dict[str, str]:
    """A drawing (or document) as text, field -> value: its choices as the items' labels, its date as dd/mm/yyyy."""
    labels = {field: {i.id: i.label() for i in getattr(enums, enum)} for field, (enum, _) in spec.choices.items()}
    out = {f: getattr(drawing, f) for f in spec.text} | {"equipment_reference": drawing.equipment_reference}
    for field in spec.choices:
        out[field] = labels[field].get(getattr(drawing, f"{field}_id") or "", "")
    out["issue_date"] = drawing.issue_date.strftime("%d/%m/%Y") if drawing.issue_date else ""
    return out
