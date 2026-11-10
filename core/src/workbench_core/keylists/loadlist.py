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
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from ..refdata.validate import name_key

#: The import targets whose rows make up the Load List.
LOAD_LIST_TARGETS = ("MEL", "EEL")

CellValue = str | float | int | bool | None
AllocatedBy = Literal["auto", "user"]


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
    updated_at: datetime | None = None  # when a person last changed its allocations


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
    """Fill in (or follow) the automatic allocations of a row; a person's choice is kept."""
    update: dict[str, object] = {}
    for kind, field, index in (("plant_area", "area", areas), ("load_type", "load_type", types)):
        if getattr(row, f"{kind}_by") == "user":
            continue
        found = auto_match(row.values.get(field), index)
        update[f"{kind}_id"] = found
        update[f"{kind}_by"] = "auto" if found else None
    return row.model_copy(update=update)
