# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Dot notation and modifiers for the generators' <<tags>>.

A tag in a load type's or an equipment type's rows is `<<path|modifier|modifier:arg>>`:

- **path**: one name, as before (`<<Tag>>`, `<<loadtypename>>`, `<<#1>>`, `<<STD>>`), or names
  joined by dots that follow the row's links to other records and end on one of their fields:
  `<<LoadType.Name>>`, `<<PlantArea.Parent.Tag>>`, `<<SuppliedFrom.LoadType.Code>>`,
  `<<Parent.Eel.EquipmentCode.Name>>`, `<<Rack.System.Tag>>`. Names are matched ignoring case,
  spaces and _ (`LoadType.StdDrg` = `loadtype.std_drg`). A path that ends on a record gives its
  name (a load's tag, a load type's code, a plant area's tag…).
- **modifiers** change the text, left to right: upper, lower, title, trim, nohyphen, int,
  round:n, dec:n, pad:n, left:n, right:n, replace:a:b, prefix:x, suffix:x, default:x.

A link the row doesn't have (no load type allocated, no parent found) gives blank, which
`default:x` can fill. A name that isn't a link or field, or a modifier that doesn't exist, leaves
the tag as it is, counted with what is wrong, like a tag that matches nothing.

SCHEMA says what each kind of record has. It is what paths are checked against and what the help
lists; the records themselves are built on demand from Links, the project's lists.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from ..refdata.validate import name_key
from ..text_case import proper_case


def norm(name: str) -> str:
    return re.sub(r"[\s_]+", "", name).casefold()


def _text(v: object) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, (list, tuple)):
        return ", ".join(_text(x) for x in v)
    return str(v).strip()


# -- what each kind of record has --------------------------------------------------------------

#: kind -> (what one is, its name field, [(field, meaning)], [(link, kind, meaning)])
SCHEMA: dict[str, tuple[str, str, list[tuple[str, str]], list[tuple[str, str, str]]]] = {
    "load": ("a load (a Load List row)", "Tag", [
        ("Tag", "tag"), ("Description", "description"), ("Rating", "rating"), ("Units", "rating's units"),
        ("Voltage", "voltage"), ("Phases", "phases"), ("Area", "area text from the import"), ("Source", "import it comes from"),
        ("IsPanel", "Yes when it is a distribution panel"), ("CableLength", "power cable's length (m)"),
        ("CableSize", "power cable's size (mm²)"), ("EarthSize", "earth cable's size"), ("CableInsulation", "cable insulation"),
        ("CableParallel", "cables in parallel"), ("CableConstruction", "Multicore or Single core"),
        ("<field>", "any Load List field, by its tag or its name (calculated fields too)"),
    ], [
        ("LoadType", "loadtype", "load type"), ("PlantArea", "area", "plant area"), ("SuppliedFrom", "load", "panel it is supplied from"),
        ("Eel", "eel", "Electrical Equipment List item (its rows only)"), ("Cable", "cable", "cable (per-cable rows only)"),
        ("Motor", "motor", "motor (Motor Data, matched by its rating and Poles)"),
        ("Drive", "drive", "drive (Drive Data, matched by voltage, Drive enclosure, Drive duty and the motor's FLC)"),
        ("Starter", "starter", "Type 2 starter (Starter Coordination, its load type's chart, matched by its rating)"),
    ]),
    "starter": ("a Type 2 starter selection", "Chart", [
        ("Chart", "coordination chart (e.g. ECH64.2)"), ("Description", "what the chart is"), ("FaultkA", "fault level Iq (kA)"),
        ("Manufacturer", "manufacturer"), ("kW", "the row's motor kW"), ("FLC", "the row's motor FLC @ 400 V (A)"),
        ("CB", "circuit breaker (e.g. ZS125M / 20A)"), ("CBAmps", "circuit breaker rating (A)"),
        ("ELSetting", "earth leakage setting range"), ("Contactor", "contactor"), ("Overload", "overload relay"),
        ("Range", "overload setting range (e.g. 5.4 – 27)"), ("RangeMin", "overload setting from (A)"),
        ("RangeMax", "overload setting to (A)"), ("InstTrip", "C/B instantaneous trip (A, ±20 %)"),
        ("MinTrip", "minimum trip as a multiple of motor FLC"), ("Note", "chart note (* or ^)"), ("NoteText", "what the note says"),
    ], []),
    "drive": ("a drive", "CatNo", [
        ("CatNo", "catalog number"), ("Manufacturer", "manufacturer"), ("Series", "range"), ("Voltage", "voltage class (V)"),
        ("VoltageRange", "voltage range"), ("Enclosure", "Open, IP54 or Flange"), ("Frame", "frame size"),
        ("Duty", "the duty it was matched on (ND/HD)"), ("Amps", "continuous output amps at the load's duty"),
        ("Amps1min", "1 min output amps at the load's duty"), ("Amps3s", "3 s output amps at the load's duty"),
        ("kW", "power (kW) at the load's duty"), ("Hp", "power (Hp) at the load's duty"),
        ("NDAmps", "Normal Duty continuous amps"), ("ND1min", "Normal Duty 1 min amps"), ("ND3s", "Normal Duty 3 s amps"),
        ("NDkW", "Normal Duty kW"), ("NDHp", "Normal Duty Hp"), ("HDAmps", "Heavy Duty continuous amps"),
        ("HD1min", "Heavy Duty 1 min amps"), ("HD3s", "Heavy Duty 3 s amps"), ("HDkW", "Heavy Duty kW"), ("HDHp", "Heavy Duty Hp"),
    ], []),
    "motor": ("a motor", "PartNo", [
        ("PartNo", "part number"), ("Manufacturer", "manufacturer"), ("Series", "range"), ("Design", "Standard or High-Output"),
        ("Poles", "poles"), ("Frame", "IEC frame"), ("kW", "output (kW)"), ("Speed", "rated speed (rpm)"),
        ("FLC", "full load current (A)"), ("ILIr", "locked rotor current (x FLC)"), ("Torque", "full load torque (Nm)"),
        ("TLTr", "locked rotor torque (x full load)"), ("TbTr", "breakdown torque (x full load)"),
        ("Eff50", "efficiency at 50 % load (%)"), ("Eff75", "efficiency at 75 % load (%)"), ("Eff100", "efficiency at full load (%)"),
        ("PF50", "power factor at 50 % load"), ("PF75", "power factor at 75 % load"), ("PF100", "power factor at full load"),
        ("Sound", "sound pressure (dB(A))"), ("Inertia", "moment of inertia (kgm²)"), ("LockedCold", "max. locked rotor time, cold (s)"),
        ("LockedHot", "max. locked rotor time, hot (s)"), ("Weight", "approximate weight (kg)"), ("Voltage", "rated voltage (V)"),
    ], []),
    "loadtype": ("a load type", "Code", [
        ("Code", "code"), ("Name", "name"), ("RatingUnit", "kW or Amps"), ("Voltage", "voltage"), ("Phases", "phases"),
        ("From", "from value"), ("To", "to value"), ("StdDrg", "STD drawing"), ("BucketType", "bucket type"),
        ("LoadType", "load type text"), ("FieldOptions", "field options"), ("MultiLoad", "multi load (Yes/No)"), ("LoadQty", "load quantity"),
        ("StarterChart", "Starter Coordination chart (blank: the project default; None: no starter)"),
    ], []),
    "component": ("a component table's row", "first column", [
        ("Min", "the row's range from"), ("Max", "the row's range to"), ("<column>", "any column of the table, e.g. PartNumber"),
    ], []),
    "area": ("a plant area", "Tag", [
        ("Tag", "tag number"), ("Description", "description"), ("Type", "type (Area, Building, Room…)"), ("WBS", "WBS"),
    ], [("Parent", "area", "parent plant area")]),
    "cable": ("a cable type", "Code", [
        ("Code", "code"), ("Application", "application"), ("Type", "type"), ("Cores", "cores"), ("Size", "size (mm²)"),
        ("Voltage", "voltage"), ("Insulation", "insulation"), ("Description", "description"),
    ], []),
    "eel": ("an Electrical Equipment List item", "Tag", [
        ("Tag", "tag"), ("Description", "description"), ("Rating", "rating"), ("RatingUnit", "kW or Amps"), ("Voltage", "voltage"),
        ("Phases", "phases"), ("Manufacturer", "manufacturer"), ("Model", "model number"), ("IsPanel", "Yes when it is a panel"),
    ], [
        ("EquipmentCode", "code", "equipment code"), ("VendorPackage", "package", "vendor package"),
        ("SuppliedBy", "package", "package it is supplied by"), ("InstalledBy", "package", "package it is installed by"),
        ("TerminatedBy", "package", "package it is terminated by"), ("PlantArea", "area", "plant area"),
        ("LoadType", "loadtype", "load type"), ("Load", "load", "Load List row"),
    ]),
    "code": ("an equipment code", "Code", [
        ("Code", "code"), ("Name", "name"), ("Description", "description"), ("Disciplines", "disciplines"),
    ], []),
    "package": ("an equipment package", "Number", [
        ("Number", "package number"), ("Description", "description"), ("Vendor", "vendor"), ("Type", "package type"),
    ], []),
    "equipmenttype": ("an equipment type", "Name", [("Name", "name"), ("Description", "description")],
                      [("Package", "package", "equipment package")]),
    "rack": ("a PLC rack", "Tag", [("Tag", "tag"), ("Description", "description"), ("FirstSlot", "first slot number")],
             [("System", "system", "PLC system"), ("PlantArea", "area", "plant area")]),
    "system": ("a PLC system", "Tag", [
        ("Tag", "tag"), ("Description", "description"), ("Manufacturer", "manufacturer"), ("Model", "model"),
    ], []),
    "runsheet": ("an Instrument Runsheet row", "", [], [
        ("EquipmentType", "equipmenttype", "equipment type"), ("PlantArea", "area", "plant area"),
        ("Parent", "load", "load its parent tag names (MEL, EEL or Load List row)"), ("Rack", "rack", "PLC List rack its Rack names"),
    ]),
}
_LINKS = {kind: {norm(n): k for n, k, _ in s[3]} for kind, s in SCHEMA.items()}
#: Kinds whose records have links of their own besides SCHEMA's: a load type's component
#: tables (<<LoadType.CB.PartNumber>>), checked when the record is there.
DYNAMIC_LINKS = {"loadtype": "component"}
_FIELDS = {kind: {norm(n) for n, _ in s[2] if not n.startswith("<")} for kind, s in SCHEMA.items()}
#: The link names a Load List field can't take (it would hide the link).
LINK_NAMES = {n for links in _LINKS.values() for n in links}


@dataclass
class Record:
    kind: str
    fields: dict[str, object]  # norm(name) -> value
    links: dict[str, Callable[[], Record | None]] = field(default_factory=dict)
    name: object = ""


# -- the project's records ---------------------------------------------------------------------

def _number(v: object) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    t = str(v).strip()
    try:
        return float(t) if t else None
    except ValueError:
        return None


def component_row(table, load: Record | None) -> Record:
    """The row of a component table a load gets: the first whose Min <= the load's match field
    <= Max (a blank bound is open). When the load has no number there or no row fits, a blank
    row (so its columns are still known, and a misspelt one is still reported)."""
    blank = Record("component", {norm(c): "" for c in table.columns} | {"min": "", "max": ""}, name="")
    x = _number(load.fields.get(norm(table.match_field))) if load is not None else None
    if x is None:
        return blank
    for r in table.rows:
        if (r.min is None or float(r.min) <= x) and (r.max is None or x <= float(r.max)):
            fields: dict[str, object] = {norm(c): r.values.get(c, "") for c in table.columns}
            fields |= {"min": r.min or "", "max": r.max or ""}
            return Record("component", fields, name=r.values.get(table.columns[0], "") if table.columns else "")
    return blank


class Links:
    """The project's lists, indexed once, for following links. Every argument is optional: a
    link to a list that isn't given is blank."""

    def __init__(self, load_types=None, areas=None, loads=None, eel=None, codes=None, packages=None, equipment_types=None,
                 cables=None, plc=None, load_labels: dict[str, str] | None = None, motors=None, drives=None, starters=None):
        self.motors = list(motors or [])
        self.starters = starters  # keylists.starters.StarterList
        self.drives = list(drives or [])
        self.load_types = {t.id: t for t in load_types or []}
        self.areas = {a.id: a for a in areas or []}
        self.loads = list(loads or [])
        self.by_ref = {r.ref(): r for r in self.loads}
        self.by_tag: dict[str, object] = {}
        for r in self.loads:  # an active row wins over a deleted one with the same tag
            k = name_key(r.tag())
            if k not in self.by_tag or (r.status == "active" and self.by_tag[k].status != "active"):  # type: ignore[attr-defined]
                self.by_tag[k] = r
        self.eel = {i.id: i for i in eel or []}
        self.codes = {c.id: c for c in codes or []}
        self.packages = {p.id: p for p in packages or []}
        self.equipment_types = {t.id: t for t in equipment_types or []}
        self.cables = {name_key(c.code): c for c in cables or []}
        self.racks: dict[str, tuple[object, object]] = {}
        for system in getattr(plc, "systems", []) or []:
            for rack in system.racks:
                self.racks.setdefault(name_key(rack.tag), (rack, system))
        self.load_labels = {norm(label): key for key, label in (load_labels or {}).items()}
        self._area_tags = {i: (a.tag, a.description) for i, a in self.areas.items()}

    # each returns None for a link that isn't there
    def load_type(self, i, load: Record | None = None):
        """A load type; with `load` (the load it is allocated to) its component tables are links
        to the row each one picks for that load."""
        t = self.load_types.get(i or "")
        if t is None:
            return None
        tables = {norm(c.name): (lambda c=c: component_row(c, load)) for c in getattr(t, "components", [])}
        return Record("loadtype", {
            "code": t.code, "name": t.name, "ratingunit": t.rating_unit, "voltage": t.voltage, "phases": t.phases,
            "from": t.from_value, "to": t.to_value, "stddrg": t.std_drg, "buckettype": t.bucket_type, "loadtype": t.load_type,
            "fieldoptions": t.field_options, "multiload": t.multi_load, "loadqty": t.load_qty,
            "starterchart": t.starter_chart}, tables, t.code)

    def area(self, i):
        a = self.areas.get(i or "")
        return None if a is None else Record("area", {"tag": a.tag, "description": a.description, "type": a.area_type, "wbs": a.wbs},
                                             {"parent": lambda: self.area(a.parent_id)}, a.tag)

    def cable(self, code: str):
        c = self.cables.get(name_key(code)) if code else None
        return None if c is None else Record("cable", {
            "code": c.code, "application": c.application, "type": c.type, "cores": c.cores, "size": c.diameter,
            "voltage": c.voltage, "insulation": c.insulation, "description": c.description}, name=c.code)

    def motor(self, flat: dict[str, object]):
        """The Motor Data row a load's rating (and units) and poles match (keylists.motors.motor_for)."""
        from .motors import motor_fields, motor_for

        m = motor_for(flat.get("rating"), flat.get("units"), flat.get("poles"), self.motors)
        return None if m is None else Record("motor", dict(motor_fields(m)), name=m.part_no)

    def drive(self, flat: dict[str, object]):
        """The Drive Data row a load matches (keylists.drives.drive_for_load), on its motor's FLC."""
        from .drives import drive_fields, drive_for_load
        from .motors import motor_for

        m = motor_for(flat.get("rating"), flat.get("units"), flat.get("poles"), self.motors)
        x = drive_for_load(flat.get("rating"), flat.get("units"), flat.get("voltage"), m.flc if m else None,
                           flat.get("drive_duty"), flat.get("drive_enclosure"), self.drives)
        return None if x is None else Record("drive", dict(drive_fields(x, flat.get("drive_duty"))), name=x.cat_no)

    def starter(self, row, flat: dict[str, object]):
        """The Starter Coordination row a load gets: its load type's chart (or the project's default),
        matched by its rating (keylists.starters.starter_for_load)."""
        from .starters import starter_fields, starter_for_load

        t = self.load_types.get(getattr(row, "load_type_id", None) or "")
        s = starter_for_load(flat.get("rating"), flat.get("units"), t.starter_chart if t else "", self.starters)
        return None if s is None else Record("starter", dict(starter_fields(s)), name=s.chart)

    def package(self, i):
        p = self.packages.get(i or "")
        return None if p is None else Record("package", {"number": p.number, "description": p.description, "vendor": p.vendor,
                                                         "type": p.package_type}, name=p.number)

    def code(self, i):
        c = self.codes.get(i or "")
        return None if c is None else Record("code", {"code": c.code, "name": c.name, "description": c.description,
                                                      "disciplines": c.disciplines}, name=c.code)

    def eel_item(self, i):
        e = self.eel.get(i or "")
        if e is None:
            return None
        from .loadlist import EEL_SOURCE

        return Record("eel", {"tag": e.tag, "description": e.description, "rating": e.rating, "ratingunit": e.rating_unit,
                              "voltage": e.voltage, "phases": e.phases, "manufacturer": e.manufacturer, "model": e.model_number,
                              "ispanel": e.is_panel}, {
            "equipmentcode": lambda: self.code(e.equipment_code_id), "vendorpackage": lambda: self.package(e.vendor_package_id),
            "suppliedby": lambda: self.package(e.supplied_by_id), "installedby": lambda: self.package(e.installed_by_id),
            "terminatedby": lambda: self.package(e.terminated_by_id), "plantarea": lambda: self.area(e.plant_area_id),
            "loadtype": lambda: self.load_type(e.load_type_id),
            "load": lambda: self.load(self.by_ref.get(f"{EEL_SOURCE}/{e.id}"))}, e.tag)

    def equipment_type(self, i):
        t = self.equipment_types.get(i or "")
        return None if t is None else Record("equipmenttype", {"name": t.name, "description": t.description},
                                             {"package": lambda: self.package(t.package_id)}, t.name)

    def rack(self, tag: str):
        found = self.racks.get(name_key(tag)) if tag.strip() else None
        if found is None:
            return None
        rack, system = found
        sys_rec = Record("system", {"tag": system.tag, "description": system.description, "manufacturer": system.manufacturer,
                                    "model": system.model}, name=system.tag)
        return Record("rack", {"tag": rack.tag, "description": rack.description, "firstslot": rack.first_slot},
                      {"system": lambda: sys_rec, "plantarea": lambda: self.area(rack.plant_area_id)}, rack.tag)

    def load(self, row, flat: dict[str, str] | None = None, cable_code: str = ""):
        """A Load List row as a record. `flat`: its tags as the generator has them (worked out if not given)."""
        if row is None:
            return None
        from .loadgen import tags_for
        from .loadlist import EEL_SOURCE, PRIMARY_SUPPLY

        PRIMARY = "Primary Supply"

        if flat is None:
            flat = tags_for(row, self.load_types, self._area_tags, self.by_ref)
        fields: dict[str, object] = {norm(k): v for k, v in row.values.items()}
        fields |= {label: row.values.get(key) for label, key in self.load_labels.items() if label not in fields}
        fields |= {norm(k): v for k, v in flat.items()}
        fields |= {"ispanel": row.is_panel, "cablelength": row.cable_length, "cablesize": row.cable_size, "earthsize": row.earth_size,
                   "cableinsulation": row.cable_insulation, "cableparallel": row.cable_parallel,
                   "cableconstruction": row.cable_construction}
        if row.supplied_from == PRIMARY_SUPPLY:
            supply: Callable[[], Record | None] = lambda: Record("load", {"tag": PRIMARY}, name=PRIMARY)  # noqa: E731
        else:
            supply = lambda: self.load(self.by_ref.get(row.supplied_from or ""))  # noqa: E731
        links = {"loadtype": lambda: self.load_type(row.load_type_id, rec), "plantarea": lambda: self.area(row.plant_area_id),
                 "suppliedfrom": supply, "eel": lambda: self.eel_item(row.key) if row.recipe_id == EEL_SOURCE else None,
                 "cable": lambda: self.cable(cable_code), "motor": lambda: self.motor(flat), "drive": lambda: self.drive(flat),
                 "starter": lambda: self.starter(row, flat)}
        rec = Record("load", fields, links, row.tag())
        return rec

    def runsheet(self, row, flat: dict[str, str]):
        """An Instrument Runsheet row as a record: its tags, and its links."""
        return Record("runsheet", {norm(k): v for k, v in flat.items()}, {
            "equipmenttype": lambda: self.equipment_type(row.equipment_type_id), "plantarea": lambda: self.area(row.plant_area_id),
            "parent": lambda: self.load(self.by_tag.get(name_key(row.parent_tag))) if row.parent_tag.strip() else None,
            "rack": lambda: self.rack(row.rack)}, row.parent_tag)


# -- modifiers ---------------------------------------------------------------------------------

_NUM = re.compile(r"^\s*-?\d+(\.\d+)?\s*$")
#: name -> (argument count, what it does, example)
MODIFIERS: dict[str, tuple[int, str, str]] = {
    "upper": (0, "UPPER CASE", "<<LoadType.Name|upper>>"),
    "lower": (0, "lower case", "<<Tag|lower>>"),
    "title": (0, "Title Case, keeping the xProper words (MCC, PLC…) as written", "<<Description|title>>"),
    "proper": (0, "the same as title", "<<Description|proper>>"),
    "trim": (0, "remove outer spaces and repeated inner ones", "<<Description|trim>>"),
    "nohyphen": (0, "remove hyphens (P-101 → P101)", "<<Tag|nohyphen>>"),
    "int": (0, "whole number, cut off (7.9 → 7)", "<<Rating|int>>"),
    "round": (1, "round to n decimals (7.46 → 7.5 with round:1)", "<<Rating|round:1>>"),
    "dec": (1, "always n decimals, as text (7.5 → 7.50 with dec:2)", "<<Rating|dec:2>>"),
    "pad": (1, "zero-pad the whole number to n digits, as text (7 → 007 with pad:3)", "<<#1|pad:3>>"),
    "left": (1, "the first n characters", "<<Tag|left:3>>"),
    "right": (1, "the last n characters", "<<Tag|right:3>>"),
    "replace": (2, "replace a with b (\\: for a colon)", "<<Tag|replace:-:_>>"),
    "prefix": (1, "add x before, only when not blank", "<<SUF|prefix:->>"),
    "suffix": (1, "add x after, only when not blank", "<<Rating|suffix: kW>>"),
    "default": (1, "x when blank", "<<LoadType.Name|default:TBA>>"),
}
#: Modifiers whose answer is text that looks like a number but must stay as written (7.50, 007).
AS_TEXT = {"dec", "pad"}


def _split(text: str, sep: str) -> list[str]:
    """Split on `sep`, where `\\sep` is a literal one."""
    parts, cur, i = [], "", 0
    while i < len(text):
        if text[i] == "\\" and i + 1 < len(text) and text[i + 1] in (sep, "\\"):
            cur += text[i + 1]
            i += 2
            continue
        if text[i] == sep:
            parts.append(cur)
            cur = ""
        else:
            cur += text[i]
        i += 1
    return parts + [cur]


def parse(inner: str) -> tuple[list[str], list[tuple[str, list[str]]]]:
    """`path|mod|mod:arg` -> (path segments, [(modifier, args)])."""
    head, *mods = _split(inner, "|")
    path = [s.strip() for s in head.split(".")]
    out = []
    for m in mods:
        name, *args = _split(m, ":")
        out.append((norm(name), args))
    return path, out


def _int_arg(args: list[str], name: str) -> int:
    try:
        n = int(args[0].strip())
    except (ValueError, IndexError):
        raise ValueError(f"{name} needs a whole number, e.g. {name}:2") from None
    if not 0 <= n <= 50:
        raise ValueError(f"{name} takes 0 to 50")
    return n


def apply(text: str, mods: list[tuple[str, list[str]]]) -> str:
    """The modifiers, left to right. Raises ValueError saying what is wrong."""
    for name, args in mods:
        spec = MODIFIERS.get(name)
        if spec is None:
            raise ValueError(f"no modifier '{name}'")
        if len(args) < spec[0]:
            raise ValueError(f"{name} needs {spec[0]} argument(s): {spec[2]}")
        num = float(text) if _NUM.match(text) else None
        if num is not None and (math.isnan(num) or math.isinf(num)):
            num = None
        if name == "upper":
            text = text.upper()
        elif name == "lower":
            text = text.lower()
        elif name in ("title", "proper"):
            text = proper_case(text)
        elif name == "trim":
            text = " ".join(text.split())
        elif name == "nohyphen":
            text = text.replace("-", "")
        elif name == "int":
            text = str(int(num)) if num is not None else text
        elif name == "round":
            n = _int_arg(args, name)
            if num is not None:
                r = round(num, n)
                text = str(int(r)) if n == 0 or float(r).is_integer() else f"{r:.{n}f}".rstrip("0").rstrip(".")
        elif name == "dec":
            n = _int_arg(args, name)
            text = f"{num:.{n}f}" if num is not None else text
        elif name == "pad":
            n = _int_arg(args, name)
            t = text.strip()
            if num is not None:
                sign = "-" if t.startswith("-") else ""
                whole, _, frac = t.lstrip("-").partition(".")
                text = sign + whole.zfill(n) + (f".{frac}" if frac else "")
        elif name == "left":
            text = text[:_int_arg(args, name)]
        elif name == "right":
            n = _int_arg(args, name)
            text = text[-n:] if n else ""
        elif name == "replace":
            text = text.replace(args[0], args[1]) if args[0] else text
        elif name == "prefix":
            text = args[0] + text if text else text
        elif name == "suffix":
            text = text + args[0] if text else text
        elif name == "default":
            text = text if text.strip() else args[0]
    return text


# -- resolving a tag ---------------------------------------------------------------------------

def _check_path(kind: str, path: list[str]) -> str | None:
    """What is wrong with a path from a record of `kind`, by SCHEMA (the data aside)."""
    for i, seg in enumerate(path):
        n = norm(seg)
        if not n:
            return "a name is missing between the dots"
        last = i == len(path) - 1
        if not last:
            if n not in _LINKS[kind] and kind in DYNAMIC_LINKS:
                kind = DYNAMIC_LINKS[kind]
                continue
            if n not in _LINKS[kind]:
                links = ", ".join(x for x, _, _ in SCHEMA[kind][3]) or "none"
                return f"'{seg}' is not a link of {SCHEMA[kind][0]} (its links: {links})"
            kind = _LINKS[kind][n]
        elif n not in _LINKS[kind] and n not in _FIELDS[kind] and kind not in ("load", "runsheet", "component") \
                and kind not in DYNAMIC_LINKS:
            fields = ", ".join(x for x, _ in SCHEMA[kind][2])
            return f"'{seg}' is not a field of {SCHEMA[kind][0]} (its fields: {fields})"
    return None


def resolve(inner: str, flat: dict[str, str], root: Record | None) -> tuple[str | None, bool, str | None]:
    """A tag's text: (text or None, keep it as text, what is wrong). `inner` is what is between
    << and >>; `flat`: the row's tags by lower-case name; `root`: the row as a record (None:
    only the flat tags, as before)."""
    path, mods = parse(inner)
    simple = len(path) == 1 and not mods
    if simple and inner.casefold() in flat:
        return flat[inner.casefold()], False, None
    if root is None and simple:
        return None, False, None
    if len(path) == 1 and path[0].casefold() in flat:
        value: object = flat[path[0].casefold()]
    elif root is None:
        return None, False, "dot notation isn't available here"
    else:
        problem = _check_path(root.kind, path)
        if problem:
            return None, False, problem
        value = ""
        cur: Record | None = root
        for i, seg in enumerate(path):
            n = norm(seg)
            last = i == len(path) - 1
            if cur is None:
                break
            if last and n in cur.fields:
                value = cur.fields[n]
            elif n in cur.links:
                cur = cur.links[n]()
                if last:
                    value = cur.name if cur is not None else ""
            elif not last and cur.kind in DYNAMIC_LINKS:
                names = ", ".join(sorted(t for t in cur.links)) or "none"
                return None, False, f"'{seg}' is not a component table of load type {cur.name} (its tables: {names})"
            elif not last:  # a link the path allows that this record doesn't have (Primary Supply's load type): blank
                cur = None
            elif last and cur.kind in ("load", "runsheet"):
                if not simple or len(path) > 1:
                    return None, False, f"'{seg}' is not a field of {SCHEMA[cur.kind][0]}"
                return None, False, None
            elif cur.kind == "component":
                cols = ", ".join(k for k in cur.fields if k not in ("min", "max"))
                return None, False, f"'{seg}' is not a column of the component table (its columns: {cols}, min, max)"
            else:
                fields = ", ".join(x for x, _ in SCHEMA[cur.kind][2])
                tables = f"; its tables: {', '.join(sorted(cur.links))}" if cur.kind in DYNAMIC_LINKS and cur.links else ""
                return None, False, f"'{seg}' is not a field of {SCHEMA[cur.kind][0]} (its fields: {fields}{tables})"
    try:
        text = apply(_text(value), mods)
    except ValueError as exc:
        return None, False, str(exc)
    return text, any(m in AS_TEXT for m, _ in mods), None


def help_paths(root: str, depth: int = 2) -> list[tuple[str, str]]:
    """The dotted tags from a record of kind `root`, following links up to `depth` deep:
    [(<<Link.Field>>, what it is)]."""
    out: list[tuple[str, str]] = []

    def walk(kind: str, prefix: str, what: str, level: int) -> None:
        for name, kind2, meaning in SCHEMA[kind][3]:
            desc = f"{what} {meaning}".strip()
            out.append((f"<<{prefix}{name}>>", f"the {desc}'s {SCHEMA[kind2][1].lower() or 'name'}"))
            for f, m in SCHEMA[kind2][2]:
                if not f.startswith("<"):
                    out.append((f"<<{prefix}{name}.{f}>>", f"the {desc}'s {m}"))
            if kind2 in DYNAMIC_LINKS:
                out.append((f"<<{prefix}{name}.<Table>.<Column>>>", f"a column of the row of one of the {desc}'s component "
                            "tables that the load's value falls in, e.g. <<LoadType.CB.PartNumber>>"))
            if level < depth:
                walk(kind2, f"{prefix}{name}.", f"{desc}'s", level + 1)

    walk(root, "", "", 1)
    return out


__all__ = ["SCHEMA", "MODIFIERS", "Links", "Record", "LINK_NAMES", "apply", "help_paths", "norm", "parse", "resolve"]
