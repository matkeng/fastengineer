# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""The project Load List: the rows of every MEL and EEL import, combined, each with a
plant area and a load type allocated to it.

The rows come live from the imports (latest file through the saved rules and mapping).
Each row is remembered by (import, key), so a row that drops out of its import stays in
the list marked deleted, with its allocations, and gets them back if it returns.

An allocation is either chosen by a person ("user"), which nothing else changes, or
filled in automatically ("auto") from the row's mapped area / load type text when that
text equals exactly one Plant Area tag number / Load Type code (ignoring case and extra
spaces). Automatic allocations follow the text when it changes.

Each row can also be a distribution panel, and is supplied from a distribution panel of
the list or from the primary supply. Both are filled in automatically the same way, from
the mapped `is_a_loadcentre` (yes/no) and `supplied_from` (a panel's tag) fields. A row
can't be supplied from itself, and panels can't feed each other in a loop.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from ..refdata.validate import name_key

#: The import targets whose rows make up the Load List.
LOAD_LIST_TARGETS = ("MEL", "EEL")
#: `supplied_from` for a row fed straight from the primary supply (else a row's ref()).
PRIMARY_SUPPLY = "primary"

CellValue = str | float | int | bool | None
AllocatedBy = Literal["auto", "user", "eel"]
#: Who set a value that automatic fill must leave alone: a person, or the Electrical Equipment List.
KEPT = ("user", "eel")
#: The Load List "import id" of the Electrical Equipment List's items (row key = the item's id).
EEL_SOURCE = "eel"


class LoadListRow(BaseModel):
    recipe_id: str
    key: str  # the import's key column value for the row
    source: str  # the import's name (as last seen)
    target: str  # MEL / EEL
    values: dict[str, CellValue] = Field(default_factory=dict)  # mapped load-list fields, as last seen
    status: Literal["active", "deleted"] = "active"
    deleted_reason: str = ""
    plant_area_id: str | None = None
    plant_area_by: AllocatedBy | None = None
    load_type_id: str | None = None
    load_type_by: AllocatedBy | None = None
    is_panel: bool = False  # a distribution panel: other rows can be supplied from it
    is_panel_by: AllocatedBy | None = None
    supplied_from: str | None = None  # PRIMARY_SUPPLY or a panel row's ref()
    supplied_from_by: AllocatedBy | None = None
    updated_at: datetime | None = None  # when a person last changed its allocations

    def ref(self) -> str:
        """How other rows refer to this one (import ids have no "/")."""
        return f"{self.recipe_id}/{self.key}"

    def tag(self) -> str:
        tag = self.values.get("tag")
        return str(tag).strip() if tag not in (None, "") else self.key


def match_index(pairs: list[tuple[str, str]]) -> dict[str, str | None]:
    """name_key(text) -> id, or None where the text belongs to more than one item."""
    out: dict[str, str | None] = {}
    for item_id, text in pairs:
        k = name_key(text)
        if k:
            out[k] = None if k in out and out[k] != item_id else item_id
    return out


def auto_match(text: CellValue, index: dict[str, str | None]) -> str | None:
    """The id whose text equals `text` (ignoring case and extra spaces), if exactly one does."""
    if text is None or isinstance(text, bool):
        return None
    return index.get(name_key(str(text)))


def apply_auto(row: LoadListRow, areas: dict[str, str | None], types: dict[str, str | None]) -> LoadListRow:
    """Fill in (or follow) the automatic plant area, load type and distribution-panel flag of a
    row; a person's choice is kept. (Supplied from comes after, see apply_auto_supply.)"""
    update: dict[str, object] = {}
    for kind, field, index in (("plant_area", "area", areas), ("load_type", "load_type", types)):
        if getattr(row, f"{kind}_by") in KEPT:
            continue
        found = auto_match(row.values.get(field), index)
        update[f"{kind}_id"] = found
        update[f"{kind}_by"] = "auto" if found else None
    if row.is_panel_by not in KEPT:
        flag = row.values.get("is_a_loadcentre")
        update["is_panel"] = flag is True
        update["is_panel_by"] = "auto" if isinstance(flag, bool) else None
    return row.model_copy(update=update)


def panel_index(rows: list[LoadListRow]) -> dict[str, str | None]:
    """name_key(tag) -> ref() of the active distribution panel with that tag (None if several)."""
    return match_index([(r.ref(), r.tag()) for r in rows if r.is_panel and r.status == "active"])


def apply_auto_supply(row: LoadListRow, panels: dict[str, str | None]) -> LoadListRow:
    """Fill in (or follow) the automatic supplied-from of a row from its `supplied_from` text."""
    if row.supplied_from_by in KEPT:
        return row
    found = auto_match(row.values.get("supplied_from"), panels)
    if found == row.ref():
        found = None
    return row.model_copy(update={"supplied_from": found, "supplied_from_by": "auto" if found else None})


def supply_loop(rows: dict[str, LoadListRow]) -> list[str]:
    """Refs of rows that are part of a supply loop (A fed from B fed from ... A)."""
    looped: set[str] = set()
    for start in rows:
        seen: list[str] = []
        ref: str | None = start
        while ref in rows and ref not in seen:
            seen.append(ref)
            ref = rows[ref].supplied_from
        if ref in seen:
            looped.update(seen[seen.index(ref):])
    return sorted(looped)
