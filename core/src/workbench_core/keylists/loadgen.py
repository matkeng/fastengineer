# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Generating the deliverable lists from the project's own lists.

The Project Load List is the runsheet: each active load, through the load type allocated to
it, produces that load type's predefined rows for a list (cable schedule, equipment list,
instrument list, PLC I/O list), with the <<tags>> in them filled from the load. The Load
List itself is a fifth list, one row per load, with no templates.

The result is a generators BuildResult, so deliverables filter, compare, freeze and export
it exactly as they do a generator build.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..generators.models import BuildResult, BuildStats, OutputRow, Scalar
from ..mel.models import ELEC_LOAD_FIELDS
from .loadlist import PRIMARY_SUPPLY, LoadListRow
from .models import LoadType


@dataclass(frozen=True)
class OutputList:
    key: str
    deliverable_type: str
    columns: tuple[str, ...]
    diff_key: str  # the column a row is recognised by when two revisions are compared
    templated: bool = True  # False: one row per load, no load type rows


LISTS: dict[str, OutputList] = {x.key: x for x in (
    OutputList("cable_schedule", "Cable Schedule", (
        "Cable Number", "From", "From Description", "To", "To Description", "Cable Type", "Cores", "Size", "Voltage",
        "Length (m)", "Route", "Remarks"), "Cable Number"),
    OutputList("equipment_list", "Equipment List", (
        "Tag", "Description", "Equipment Type", "Plant Area", "Rating", "Units", "Voltage", "Phases", "Supplied From",
        "Manufacturer", "Model", "Remarks"), "Tag"),
    OutputList("instrument_list", "Instrument List", (
        "Tag", "Description", "Instrument Type", "Plant Area", "Service", "Signal", "IO Type", "Range", "Units", "Remarks"),
        "Tag"),
    OutputList("plc_io_list", "PLC I/O List", (
        "Tag", "Description", "Signal", "IO Type", "PLC System", "Rack", "Slot", "Channel", "Plant Area", "Remarks"), "Tag"),
    OutputList("load_list", "Load List", (
        "Tag", "Description", "Plant Area", "Load Type", "Rating", "Units", "Voltage", "Phases", "Supplied From",
        "Distribution Panel"), "Tag", templated=False),
)}
#: The lists a load type has rows for.
TEMPLATE_LISTS = [k for k, x in LISTS.items() if x.templated]
BY_TYPE = {x.deliverable_type: x for x in LISTS.values()}

#: The tags a template row can use, with what each stands for (shown in the editor).
TAGS: list[tuple[str, str]] = [
    ("Tag", "the load's tag number"), ("Description", "the load's description"), ("Area", "the area text from the import"),
    ("Rating", "the load rating"), ("Units", "kW or Amps (the load's, else the load type's)"),
    ("Voltage", "the load's voltage, else the load type's"), ("Phases", "the load's phases, else the load type's"),
    ("EquipType", "the equipment type from the import"), ("Qty", "the quantity from the import"),
    ("PlantArea", "tag number of the allocated plant area"), ("PlantAreaDesc", "its description"),
    ("LoadType", "code of the allocated load type"), ("LoadTypeName", "its name"),
    ("SuppliedFrom", "tag of the panel it is supplied from, or Primary Supply"), ("SuppliedFromDesc", "that panel's description"),
    ("StdDrg", "the load type's STD Drg"), ("BucketType", "the load type's bucket type"),
    ("Source", "the import or list the load comes from"), ("Row", "1, 2, ... within the load's rows of this list"),
]

_TAG = re.compile(r"<<\s*([^<>]+?)\s*>>")
_NUMBER = re.compile(r"^-?\d+(\.\d+)?$")


def _text(v: object) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return str(v).strip()


def _cell(text: str) -> Scalar:
    """Numbers stay numbers in the output (so they sort and export as numbers)."""
    t = text.strip()
    if _NUMBER.match(t) and not (len(t) > 1 and t[0] == "0" and t[1] != "."):
        return float(t) if "." in t else int(t)
    return t


def ordered(loads: list[LoadListRow]) -> list[LoadListRow]:
    """The active loads, by source and then tag (numbers within tags in number order)."""
    def key(r: LoadListRow):
        return (r.source.casefold(), [int(p) if p.isdigit() else p.casefold() for p in re.split(r"(\d+)", r.tag())])
    return sorted((r for r in loads if r.status == "active"), key=key)


def missing_load_types(loads: list[LoadListRow], load_types: dict[str, LoadType]) -> list[str]:
    """Tags of the active loads with no (existing) load type allocated."""
    return [r.tag() for r in ordered(loads) if r.load_type_id not in load_types]


def tags_for(row: LoadListRow, load_types: dict[str, LoadType], areas: dict[str, tuple[str, str]],
             by_ref: dict[str, LoadListRow]) -> dict[str, str]:
    """Tag name (lower case) -> text for one load. `areas`: plant area id -> (tag, description)."""
    v = row.values
    lt = load_types.get(row.load_type_id or "")
    area = areas.get(row.plant_area_id or "", ("", ""))
    supply = by_ref.get(row.supplied_from or "")
    # every load-list field by its own name (blank when the import doesn't map it)
    out = {f: "" for f in ELEC_LOAD_FIELDS} | {k.casefold(): _text(x) for k, x in v.items()}
    out |= {
        "tag": row.tag(), "description": _text(v.get("desc")), "area": _text(v.get("area")),
        "rating": _text(v.get("load_rating")), "units": _text(v.get("load_units")) or (lt.rating_unit if lt else ""),
        "voltage": _text(v.get("load_voltage")) or (_text(lt.voltage) if lt else ""),
        "phases": _text(v.get("phases")) or (lt.phases if lt else ""),
        "equiptype": _text(v.get("equip_type")), "qty": _text(v.get("equip_qty")),
        "plantarea": area[0], "plantareadesc": area[1],
        "loadtype": lt.code if lt else "", "loadtypename": lt.name if lt else "",
        "suppliedfrom": "Primary Supply" if row.supplied_from == PRIMARY_SUPPLY else (supply.tag() if supply else ""),
        "suppliedfromdesc": _text(supply.values.get("desc")) if supply else "",
        "stddrg": lt.std_drg if lt else "", "buckettype": lt.bucket_type if lt else "", "source": row.source,
    }
    return out


def expand(text: str, tags: dict[str, str], unresolved: dict[str, int]) -> str:
    def sub(m: re.Match) -> str:
        name = m.group(1).casefold()
        if name in tags:
            return tags[name]
        unresolved[m.group(0)] = unresolved.get(m.group(0), 0) + 1
        return m.group(0)
    return _TAG.sub(sub, text)


def generate(list_key: str, loads: list[LoadListRow], load_types: dict[str, LoadType],
             areas: dict[str, tuple[str, str]]) -> BuildResult:
    """The rows of one list for the active loads. `load_types` by id; `areas`: plant area id ->
    (tag, description). Loads without a load type produce nothing in a templated list (the
    caller reports them: see missing_load_types)."""
    spec = LISTS[list_key]
    by_ref = {r.ref(): r for r in loads}
    unresolved: dict[str, int] = {}
    rows: list[OutputRow] = []
    for load in ordered(loads):
        tags = tags_for(load, load_types, areas, by_ref)
        lt = load_types.get(load.load_type_id or "")
        if not spec.templated:
            cells = [tags["tag"], tags["description"], tags["plantarea"], tags["loadtype"], tags["rating"], tags["units"],
                     tags["voltage"], tags["phases"], tags["suppliedfrom"], "Yes" if load.is_panel else ""]
            rows.append(OutputRow(cells=[_cell(c) for c in cells], run_row_id=load.ref(), template_id=lt.code if lt else None))
            continue
        for i, template in enumerate((lt.rows.get(list_key, []) if lt else []), start=1):
            tags["row"] = str(i)
            rows.append(OutputRow(cells=[_cell(expand(template.get(c, ""), tags, unresolved)) for c in spec.columns],
                                  run_row_id=load.ref(), template_id=lt.code, template_seq=i))
    return BuildResult(header=list(spec.columns), rows=rows, stats=BuildStats(rows_written=len(rows), output_rows=len(rows)),
                       unresolved_tokens=sorted(unresolved), unresolved_count=sum(unresolved.values()),
                       engine_version="load types")
