# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""The project's Enums: the choice lists that other lists pick from.

- **Disciplines**: used by Equipment Codes (which keep a discipline by its code) and by the
  Drawing List. Every discipline has a code.
- **Drawing types** and **Drawing statuses**: used by the Drawing List. A code is optional
  (a status is usually known by its code, IFC; a drawing type by its name).

A project starts with a default set and can change it: add, rename, reorder and remove items.
Within an enum, codes are unique and names are unique (ignoring case and extra spaces). An
item is referred to by its id, so renaming one changes nothing elsewhere; the engine refuses
to remove an item that is in use.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from ..refdata.models import RefValidationError, new_id
from ..refdata.validate import name_key
from .models import DISCIPLINES

#: enum key -> (what it is called, what one item is called, whether every item needs a code)
ENUMS: dict[str, tuple[str, str, bool]] = {
    "disciplines": ("Disciplines", "discipline", True),
    "drawing_types": ("Drawing types", "drawing type", False),
    "drawing_statuses": ("Drawing statuses", "drawing status", False),
}
DRAWING_TYPES: tuple[str, ...] = (
    "Single Line Diagram", "Schematic", "Termination Diagram", "Loop Diagram", "Block Diagram", "Cable Block Diagram", "Layout",
    "General Arrangement", "P&ID", "Hook-up", "Panel Schedule", "Schedule", "Index", "Standard Detail", "Datasheet", "Other")
#: (code, name) of the statuses a project starts with.
DRAWING_STATUSES: tuple[tuple[str, str], ...] = (
    ("", "Draft"), ("IFR", "Issued for Review"), ("IFA", "Issued for Approval"), ("IFT", "Issued for Tender"),
    ("IFC", "Issued for Construction"), ("AB", "As Built"), ("", "Superseded"), ("", "Cancelled"))


class EnumItem(BaseModel):
    id: str = Field(default_factory=new_id)
    code: str = ""
    name: str

    def label(self) -> str:
        """What a list shows for the item: its code when it has one, else its name."""
        return self.code or self.name


class ProjectEnums(BaseModel):
    disciplines: list[EnumItem] = Field(default_factory=list)
    drawing_types: list[EnumItem] = Field(default_factory=list)
    drawing_statuses: list[EnumItem] = Field(default_factory=list)
    updated_at: datetime | None = None


def default_enums() -> ProjectEnums:
    """What a project has until it saves its own (ids are fixed, so a default item keeps its
    identity when the enums are first saved)."""
    return ProjectEnums(
        disciplines=[EnumItem(id=f"d-{c.lower()}", code=c, name=n) for c, n in DISCIPLINES.items()],
        drawing_types=[EnumItem(id=f"dt{i}", name=n) for i, n in enumerate(DRAWING_TYPES, start=1)],
        drawing_statuses=[EnumItem(id=f"ds{i}", code=c, name=n) for i, (c, n) in enumerate(DRAWING_STATUSES, start=1)])


def check_enums(enums: ProjectEnums) -> ProjectEnums:
    """Trimmed and checked: a name is required; a discipline needs a code; codes and names are
    unique within their enum. Errors are `<item id>.code` / `<item id>.name` -> message."""
    errors: dict[str, str] = {}
    out: dict[str, list[EnumItem]] = {}
    ids: set[str] = set()
    for key, (_title, what, need_code) in ENUMS.items():
        items = []
        seen: dict[str, set[str]] = {"code": set(), "name": set()}
        for raw in getattr(enums, key):
            item = raw.model_copy(update={"code": raw.code.strip(), "name": " ".join(raw.name.split())})
            if item.id in ids:
                raise RefValidationError("Two items have the same id.", {f"{item.id}.name": "Duplicate item"})
            ids.add(item.id)
            if not item.name:
                errors[f"{item.id}.name"] = "Name is required"
            if need_code and not item.code:
                errors[f"{item.id}.code"] = f"A {what} needs a code"
            for field in ("code", "name"):
                k = name_key(getattr(item, field))
                if k and k in seen[field]:
                    errors[f"{item.id}.{field}"] = f"{field.capitalize()} '{getattr(item, field)}' is used twice"
                seen[field].add(k)
            items.append(item)
        out[key] = items
    if errors:
        raise RefValidationError(f"{len(errors)} problem(s) in the enums.", errors)
    return ProjectEnums(**out)


def lookup(items: list[EnumItem]) -> dict[str, str]:
    """name_key(code) and name_key(name) -> item id, to find an item typed as either."""
    out: dict[str, str] = {}
    for i in items:
        for text in (i.code, i.name):
            if name_key(text):
                out.setdefault(name_key(text), i.id)
    return out
