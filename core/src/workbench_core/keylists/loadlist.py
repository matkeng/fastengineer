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
CableConstruction = Literal["Multicore", "Single core"]
CABLE_CONSTRUCTIONS: tuple[str, ...] = ("Multicore", "Single core")
#: The cable details a person types in on a row (not allocations: nothing fills them in).
CABLE_FIELDS = ("cable_length", "cable_construction", "cable_parallel", "cable_insulation", "cable_size", "earth_size")
#: A person's overrides of the row's Load Factors (keylists.load_factors): blank uses the list's.
FACTOR_FIELDS = ("lf_nameplate", "lf_optimised", "lf_avg_demand", "lf_max_demand")


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
    # The load's power cable, typed in by a person (cable sizing is done outside the app). The
    # cable schedule finds the matching row of the Cable Types list from these.
    cable_length: float | None = None  # metres
    cable_construction: CableConstruction | None = None  # None counts as multicore
    cable_parallel: int | None = None  # cables (or single-core sets) run in parallel; None counts as 1
    cable_insulation: str = ""  # an Insulation value of the Cable Types list
    cable_size: str = ""  # core size, mm2 (a Diameter value of the Cable Types list)
    earth_size: str = ""  # the separate earth cable of a single-core set, mm2
    # Load factors typed in by a person, overriding the Load Factors list's for this row (None: the list's).
    lf_nameplate: float | None = None
    lf_optimised: float | None = None
    lf_avg_demand: float | None = None
    lf_max_demand: float | None = None
    updated_at: datetime | None = None  # when a person last changed its allocations
    #: What is wrong with its calculated fields (keylists.load_calcs): [{field, severity, message}].
    #: Worked out with them each time the Load List is read; not kept.
    calc_issues: list[dict[str, str]] = Field(default_factory=list)
    #: Its effective load factors (keylists.load_factors.effective_factors), worked out each time
    #: the Load List is read; not kept. Includes "list" (the list's values) and "source".
    factors: dict[str, object] = Field(default_factory=dict)

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


HP_KW = 0.7457
#: name_key(code) -> the load types of that code: (id, rating unit, from, to); a blank bound is None (open).
LoadTypeIndex = dict[str, list[tuple[str, str, float | None, float | None]]]


def load_type_range(t) -> str:
    """A load type's range in words: "0.37–11 kW", "≤ 11 kW", "≥ 11 kW", or "any kW"."""
    lo, hi = t.from_value, t.to_value
    text = f"{lo}–{hi}" if lo is not None and hi is not None else f"≥ {lo}" if lo is not None else f"≤ {hi}" if hi is not None else "any"
    return f"{text} {t.rating_unit}"


def load_type_label(t) -> str:
    """How a load type is told from others of its code: "DOL 0.37–11 kW"."""
    return f"{t.code} {load_type_range(t)}"


def load_type_choice(t, types: list) -> str:
    """A load type in a list of choices: "DOL – Direct on line starter"; with its range when
    other load types have its code: "DOL 0.37–11 kW – Direct on line starter"."""
    shared = sum(1 for x in types if name_key(x.code) == name_key(t.code)) > 1
    return f"{load_type_label(t) if shared else t.code} – {t.name}"


def load_type_names(types: list) -> list[tuple[str, str]]:
    """(id, text) of each load type, as a workbook names it: its code, or "DOL 0.37–11 kW" when
    other load types have its code."""
    count: dict[str, int] = {}
    for t in types:
        count[name_key(t.code)] = count.get(name_key(t.code), 0) + 1
    return [(t.id, t.code if count[name_key(t.code)] == 1 else load_type_label(t)) for t in types]


def load_type_index(types: list) -> LoadTypeIndex:
    """The load types by code, for match_load_type."""
    out: LoadTypeIndex = {}
    for t in types:
        k = name_key(t.code)
        if k:
            out.setdefault(k, []).append((t.id, t.rating_unit, None if t.from_value is None else float(t.from_value),
                                          None if t.to_value is None else float(t.to_value)))
    return out


def rating_in_unit(rating: CellValue, units: CellValue) -> tuple[float | None, str | None]:
    """A load's rating and the load types' unit it is in: kW (blank units too; HP converted,
    × 0.7457) or Amps (A, Amp, Amps). (None, unit) for no rating; (None, None) for other units."""
    u = "" if units is None or isinstance(units, bool) else str(units).strip().casefold()
    unit = "kW" if u in ("", "kw") or u == "hp" else "Amps" if u in ("a", "amp", "amps") else None
    try:
        r = None if rating is None or isinstance(rating, bool) or str(rating).strip() == "" else float(str(rating).replace(",", ""))
    except ValueError:
        r = None
    if unit is None or r is None:
        return None, unit
    return (r * HP_KW if u == "hp" else r), unit


def match_load_type(code: CellValue, rating: CellValue, units: CellValue, index: LoadTypeIndex) -> tuple[str | None, str]:
    """The load type a load gets: of its code (ignoring case and extra spaces), with the load's
    unit as its rating unit, and a range (both ends included; a blank end is open) that includes
    the load's rating. Returns (id, "") or (None, why): "no code" (blank, or no load type has
    it), "no rating" (the code is known but the rating is blank or its units aren't kW, HP or
    Amps), "no range" (no load type of that code and unit has a range the rating is in)."""
    if code is None or isinstance(code, bool) or name_key(str(code)) not in index:
        return None, "no code"
    r, unit = rating_in_unit(rating, units)
    if r is None:
        return None, "no rating"
    for type_id, type_unit, lo, hi in index[name_key(str(code))]:
        if type_unit == unit and (lo is None or lo - 1e-9 <= r) and (hi is None or r <= hi + 1e-9):
            return type_id, ""
    return None, "no range"


def apply_auto(row: LoadListRow, areas: dict[str, str | None], types: LoadTypeIndex) -> LoadListRow:
    """Fill in (or follow) the automatic plant area, load type and distribution-panel flag of a
    row; a person's choice is kept. (Supplied from comes after, see apply_auto_supply.) The load
    type is matched on the row's load type code, rating and units (match_load_type)."""
    update: dict[str, object] = {}
    if row.plant_area_by not in KEPT:
        found = auto_match(row.values.get("area"), areas)
        update |= {"plant_area_id": found, "plant_area_by": "auto" if found else None}
    if row.load_type_by not in KEPT:
        found, _ = match_load_type(row.values.get("load_type"), row.values.get("load_rating"), row.values.get("load_units"), types)
        update |= {"load_type_id": found, "load_type_by": "auto" if found else None}
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
