# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Generating the deliverable lists from the project's own lists.

The Project Load List is the runsheet: each active load, through the load type allocated to
it, produces that load type's predefined rows for a list (cable schedule, equipment list,
instrument list, PLC I/O list), with the <<tags>> in them filled from the load. The Load
List itself is a fifth list, one row per load, with no templates.

The result is a generators BuildResult, so deliverables filter, compare, freeze and export
it exactly as they do a generator build.

Cables: a load carries its power cable's details (size, insulation, multicore or single
core, how many in parallel, length), typed in on the Load List. A cable schedule row can
be marked "Per power cable": it is then produced once per cable (one per parallel
multicore cable; for single core, one per phase conductor per parallel set, and one earth
cable), and each cable is looked up in the Cable Types list.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..generators.models import BuildResult, BuildStats, OutputRow, Scalar
from ..mel.models import ELEC_LOAD_FIELDS
from ..refdata.validate import name_key
from .cable_types import CableType
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
        "Cable Number", "From", "From Description", "To", "To Description", "Cable Type", "Cable Code", "Cores", "Size", "Voltage",
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
#: The Load List's cable columns, after its own (the load's power cable, typed in on the Load List).
LOAD_LIST_CABLE: tuple[str, ...] = ("Cable Length (m)", "Power Cable", "Parallel Cables", "Cable Insulation", "Cable Size",
                                    "Earth Size")


def load_list_columns(load_fields=None) -> list[tuple[str, str]]:
    """The columns of the Load List deliverable's content, the Project Master Load List:
    (name, what fills it). Its own columns, the cable columns, then each of the project's
    Load List fields but the tag and description (`load_fields`: mel.load_fields.LoadFields;
    default the built-in ones), by their names; a name already used gets " (import)"."""
    from ..mel.load_fields import default_load_fields

    out = [(c, f"col:{c}") for c in LISTS["load_list"].columns] + [(c, f"col:{c}") for c in LOAD_LIST_CABLE]
    seen = {name_key(c) for c, _ in out}
    for f in (load_fields or default_load_fields()).fields:
        if f.key in ("tag", "desc"):
            continue
        name = f.label if name_key(f.label) not in seen else f"{f.label} (import)"
        n = 2
        while name_key(name) in seen:
            name, n = f"{f.label} ({n})", n + 1
        seen.add(name_key(name))
        out.append((name, f"field:{f.key}"))
    return out


#: The lists a load type has rows for.
TEMPLATE_LISTS = [k for k, x in LISTS.items() if x.templated]
BY_TYPE = {x.deliverable_type: x for x in LISTS.values()}

#: A cable schedule row's extra setting (kept with the row's cells; not an output column).
REPEAT = "Repeat"
PER_CABLE = "Per power cable"
#: Settings a list's template rows can have besides its columns: list key -> {name: allowed values}.
ROW_SETTINGS: dict[str, dict[str, tuple[str, ...]]] = {"cable_schedule": {REPEAT: (PER_CABLE,)}}

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
    ("CableNo", "1, 2, ... for each cable a 'Per power cable' row produces"),
    ("Phase", "L1, L2, L3, N or E for a single-core cable (blank for multicore)"),
    ("CableCode", "code of the matching cable in Cable Types"), ("CableDesc", "its description"),
    ("CableCores", "its cores (1C for single core)"), ("CableSize", "the load's core size (the earth size on an earth cable)"),
    ("CableInsulation", "the load's cable insulation"), ("CableVoltage", "the matching cable's voltage grade"),
    ("CableLength", "the load's cable length (m)"), ("CableParallel", "how many cables run in parallel"),
    ("CableConstruction", "Multicore or Single core"),
]
_CABLE_TAGS = ("cableno", "phase", "cablecode", "cabledesc", "cablecores", "cablesize", "cableinsulation", "cablevoltage",
               "cablelength", "cableparallel", "cableconstruction")

_TAG = re.compile(r"<<\s*([^<>]+?)\s*>>")


def tag_names(load_fields=None) -> set[str]:
    """Every name a load answers to in a tag, as tag_paths.norm gives it: TAGS, the cable tags,
    and the project's Load List fields by key and by name (`load_fields`: mel.load_fields.LoadFields)."""
    from .tag_paths import norm

    out = {norm(t) for t, _ in TAGS} | set(_CABLE_TAGS) | {norm(f) for f in ELEC_LOAD_FIELDS}
    out |= {"row", "ispanel", "earthsize", "lfnameplate", "lfoptimised", "lfavgdemand", "lfmaxdemand"}
    for f in (load_fields.fields if load_fields is not None else []):
        out |= {norm(f.key), norm(f.label)}
    return out


def check_rows(rows: dict[str, list[dict[str, str]]], kind: str, names: dict[str, set[str]],
               tables: dict[str, set[str]] | None = None) -> dict[str, list[dict]]:
    """What is wrong with the tags in a type's predefined rows, as they are written: list key ->
    [{row, column, tag, problem}] (`row` counts from 0). See tag_paths.check."""
    from .tag_paths import check

    out: dict[str, list[dict]] = {}
    for key, list_rows in rows.items():
        for i, row in enumerate(list_rows):
            for column, text in row.items():
                for m in _TAG.finditer(str(text)):
                    problem = check(m.group(1), kind, names, tables)
                    if problem:
                        out.setdefault(key, []).append({"row": i, "column": column, "tag": m.group(0), "problem": problem})
    return out
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


def expand(text: str, tags: dict[str, str], unresolved: dict[str, int], root=None, as_text: list[bool] | None = None) -> str:
    """The text with its <<tags>> filled in from `tags` (lower-case name -> text). `root`: the
    row as a tag_paths.Record, for dot notation and modifiers (<<LoadType.Name|upper>>); without
    it only the plain tags are filled in. A tag that matches nothing is left as it is and
    counted in `unresolved` (with what is wrong when it says). `as_text` gets True when a
    modifier made text that must not become a number (dec, pad)."""
    from .tag_paths import resolve

    def sub(m: re.Match) -> str:
        name = m.group(1)
        if name.casefold() in tags:
            return tags[name.casefold()]
        value, keep, problem = resolve(name, tags, root)
        if value is not None:
            if keep and as_text is not None:
                as_text.append(True)
            return value
        key = m.group(0) if problem is None else f"{m.group(0)} ({problem})"
        unresolved[key] = unresolved.get(key, 0) + 1
        return m.group(0)
    return _TAG.sub(sub, text)


def expand_cell(text: str, tags: dict[str, str], unresolved: dict[str, int], root=None) -> Scalar:
    """A template cell filled in, as a cell: a number stays a number, unless a modifier made it text."""
    keep: list[bool] = []
    out = expand(text, tags, unresolved, root, keep)
    return out.strip() if keep else _cell(out)


# -- cables ------------------------------------------------------------------------------------

def _size(text: str) -> str:
    """Sizes compare as numbers where they are numbers ("2.50" = "2.5"), else as text."""
    t = text.strip().replace("mm2", "").replace("mm²", "").strip()
    try:
        return f"{float(t):g}"
    except ValueError:
        return name_key(t)


def match_cable(cables: list[CableType], kind: str, cores: str, size: str, insulation: str = "", voltage: str = "",
                application: str = "") -> tuple[CableType | None, str]:
    """The one cable type with this type (family), cores, size and insulation; blank
    criteria are not compared. Several left: the one whose application names the voltage
    ("AC_415V" for 415). Returns (cable, why not)."""
    def same(have: str, want: str) -> bool:
        return not want.strip() or name_key(have) == name_key(want)
    found = [c for c in cables if same(c.type, kind) and same(c.cores, cores) and same(c.insulation, insulation)
             and same(c.application, application) and _size(c.diameter) == _size(size)]
    if len(found) > 1 and voltage.strip():
        by_voltage = [c for c in found if voltage.strip() in c.application]
        found = by_voltage or found
    if len(found) == 1:
        return found[0], ""
    what = " ".join(x for x in (kind, cores, f"{size} mm²", insulation) if x.strip())
    return None, (f"no cable type is {what}" if not found else f"{len(found)} cable types are {what}")


def _phases(phases: str) -> list[str]:
    """The conductors of a single-core set, from the load's phases."""
    p = phases.casefold()
    if "dc" in p:
        return ["+", "-"]
    if "1-phase-ln" in p:
        return ["L", "N"]
    if "1-phase-ll" in p:
        return ["L1", "L2"]
    return ["L1", "L2", "L3"] + (["N"] if "+n" in p else [])


def cables_for(load: LoadListRow, kind: str, cores: str, tags: dict[str, str], cables: list[CableType],
               every: bool) -> tuple[list[dict[str, str]], list[str]]:
    """The cables one template row stands for: (cable tags per cable, problems).

    `kind` / `cores`: the row's Cable Type and Cores cells (the cable family, and the cores
    of a multicore cable). `every`: a "Per power cable" row, so one entry per cable; else
    just the first cable (as if multicore)."""
    parallel = load.cable_parallel or 1
    single = load.cable_construction == "Single core" and every
    common = {"cableinsulation": load.cable_insulation, "cablelength": _text(load.cable_length),
              "cableparallel": str(parallel), "cableconstruction": "Single core" if single else "Multicore"}
    problems: list[str] = []

    def one(phase: str, k: str, c: str, size: str, insulation: str, application: str = "") -> dict[str, str]:
        found, why = (None, "its cable size is not set") if not size.strip() else match_cable(
            cables, k, c, size, insulation, tags.get("voltage", ""), application)
        if found is None and why not in problems:
            problems.append(why)
        return common | {"phase": phase, "cablesize": size, "cablecores": found.cores if found else c,
                         "cabletype": found.type if found else k, "cablecode": found.code if found else "",
                         "cabledesc": found.description if found else "", "cablevoltage": found.voltage if found else ""}

    if not single:
        out = [one("", kind, cores, load.cable_size, load.cable_insulation) for _ in range(parallel if every else 1)]
    else:
        out = [one(p, kind, "1C", load.cable_size, load.cable_insulation) for _ in range(parallel) for p in _phases(tags.get("phases", ""))]
        earth = one("E", "", "1C", load.earth_size, "", "Earth")
        if not load.earth_size.strip():
            problems[:] = [p for p in problems if p != "its cable size is not set"] + ["its earth cable size is not set"]
        out.append(earth | {"cabletype": earth["cabletype"] or "Earth", "cableinsulation": ""})
    for n, c in enumerate(out, start=1):
        c["cableno"] = str(n)
    return out, problems


def _value(x: object) -> Scalar:
    """A Load List value as a cell: numbers stay numbers, yes/no is Yes or blank, nothing is blank."""
    if x is None:
        return ""
    if isinstance(x, bool):
        return "Yes" if x else ""
    if isinstance(x, (int, float)):
        return x
    return _cell(str(x))


def generate(list_key: str, loads: list[LoadListRow], load_types: dict[str, LoadType],
             areas: dict[str, tuple[str, str]], cables: list[CableType] | None = None,
             notes: list[str] | None = None, columns: list[str] | None = None, load_fields=None, links=None,
             only: set[str] | None = None) -> BuildResult:
    """The rows of one list for the active loads. `load_types` by id; `areas`: plant area id ->
    (tag, description). Loads without a load type produce nothing in a templated list (the
    caller reports them: see missing_load_types). `cables`: the Cable Types list, for rows
    that use the cable tags; `notes` collects the loads whose cable could not be found.
    `columns`: the project's columns for a templated list (default: the built-in ones).
    `load_fields`: the project's Load List fields, for the Load List's own (see load_list_columns).
    `links`: the project's lists (tag_paths.Links) for dot notation in the rows' tags (default:
    only what is given here). `only`: the refs of the loads to write rows for (default: all)."""
    spec = LISTS[list_key]
    cols = tuple(columns) if columns is not None and spec.templated else spec.columns
    if not spec.templated:
        whole = load_list_columns(load_fields)
        cols = tuple(c for c, _ in whole)
    cables = cables or []
    unmatched: dict[str, list[str]] = {}  # problem -> load tags
    by_ref = {r.ref(): r for r in loads}
    unresolved: dict[str, int] = {}
    rows: list[OutputRow] = []
    if links is None and spec.templated:
        from .tag_paths import Links
        links = Links(load_types=load_types.values(), loads=loads, cables=cables)
    for load in ordered(loads):
        if only is not None and load.ref() not in only:
            continue
        tags = tags_for(load, load_types, areas, by_ref)
        lt = load_types.get(load.load_type_id or "")
        if not spec.templated:
            own = [tags["tag"], tags["description"], tags["plantarea"], tags["loadtype"], tags["rating"], tags["units"],
                   tags["voltage"], tags["phases"], tags["suppliedfrom"], "Yes" if load.is_panel else ""]
            cable = [load.cable_length, load.cable_construction, load.cable_parallel, load.cable_insulation, load.cable_size,
                     load.earth_size]
            fixed = dict(zip(spec.columns + LOAD_LIST_CABLE, [_cell(c) for c in own] + [_value(c) for c in cable]))
            cells = [fixed[src[4:]] if src.startswith("col:") else _value(load.values.get(src[6:])) for _, src in whole]
            rows.append(OutputRow(cells=cells, run_row_id=load.ref(), template_id=lt.code if lt else None))
            continue
        for i, template in enumerate((lt.rows.get(list_key, []) if lt else []), start=1):
            tags["row"] = str(i)
            every = template.get(REPEAT) == PER_CABLE
            uses = every or any(m.casefold().split("|")[0].strip() in _CABLE_TAGS or m.casefold().replace(" ", "").startswith("cable.")
                                for cell in template.values() for m in _TAG.findall(cell))
            if not uses:
                for t in _CABLE_TAGS:
                    tags.pop(t, None)
                found = [{}]
            else:
                # the row's own Cable Type and Cores cells say which family of cable is wanted
                kind, cores = (expand(template.get(c, ""), tags | dict.fromkeys(_CABLE_TAGS, ""), {}) for c in ("Cable Type", "Cores"))
                found, problems = cables_for(load, kind, cores, tags, cables, every)
                for p in problems:
                    unmatched.setdefault(p, []).append(load.tag())
            for cable in found:
                row_tags = tags | cable
                root = links.load(load, row_tags, cable.get("cablecode", ""))
                cells: dict[str, Scalar] = {c: expand_cell(template.get(c, ""), row_tags, unresolved, root) for c in cols}
                if every:  # what was matched, whatever the template's cells say
                    cells |= {"Cable Type": _cell(cable["cabletype"]), "Cores": _cell(cable["cablecores"])}
                    cells["Cable Code"] = cells.get("Cable Code") or cable["cablecode"]
                rows.append(OutputRow(cells=[cells.get(c, "") for c in cols], run_row_id=load.ref(),
                                      template_id=lt.code, template_seq=i))
    if notes is not None:
        for problem, tags_ in unmatched.items():
            names = list(dict.fromkeys(tags_))
            notes.append(f"No cable for {len(names)} load(s) ({problem}): " + ", ".join(names[:12])
                         + (f" and {len(names) - 12} more" if len(names) > 12 else ""))
    return BuildResult(header=list(cols), rows=rows, stats=BuildStats(rows_written=len(rows), output_rows=len(rows)),
                       unresolved_tokens=sorted(unresolved), unresolved_count=sum(unresolved.values()),
                       engine_version="load types")
