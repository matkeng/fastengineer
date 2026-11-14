# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Starter Coordination: Type 2 coordinated direct on line starter selections (circuit breaker,
contactor, overload) by motor kW, a flat key list every project starts with NHP's six charts in
(starter_data_nhp: 50 kA and 65 kA, CEP7 or E300 overloads, Sprecher+Schuh or Allen-Bradley
contactors).

Which chart a load's starter comes from is set on its **load type** (`starter_chart`): blank
uses the project's default chart (`StarterList.default_chart`, ECH64.2: 65 kA, CA7/CA9 with
CEP7-1EF), and "None" means the load type has no starter (a drive, a panel…). The load gets the
chart's row for the smallest motor at least its kW (a rating in Hp is converted; a rating in
Amps is matched on the chart's FLC). Template rows and calculated fields reach it as
<<Starter.CB>>, <<Starter.Contactor>>, <<Starter.Overload>>, <<Starter.Range>>… (keylists.tag_paths,
load_calcs).
"""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, Field

from ..refdata.models import RefValidationError, new_id
from ..refdata.validate import name_key
from .starter_data_nhp import NHP_TYPE2
from .drives import VOLTAGE_RANGES, class_range, flc_at, voltage_class
from .units import rating_kw, unit_kind

DEFAULT_CHART = "ECH64.2"
NO_STARTER = "None"
#: The built-in charts: chart -> (fault level kA, what it is).
CHARTS: dict[str, tuple[int, str]] = {
    "ECH54.2": (50, "50 kA, Terasaki ZS + Sprecher+Schuh CA7/CA9 + CEP7-1EF electronic overload"),
    "ECH54.12": (50, "50 kA, Terasaki ZS + Sprecher+Schuh CA7/CA9 + E300 overload (EtherNet/IP)"),
    "RECH54.23": (50, "50 kA, Terasaki ZS + Allen-Bradley 100-C/100-E + E300 overload (EtherNet/IP)"),
    "ECH64.2": (65, "65 kA, Terasaki ZS + Sprecher+Schuh CA7/CA9 + CEP7-1EF electronic overload"),
    "ECH64.13": (65, "65 kA, Terasaki ZS + Sprecher+Schuh CA7/CA9 + E300 overload (EtherNet/IP)"),
    "RECH64.24": (65, "65 kA, Terasaki ZS + Allen-Bradley 100-C/100-E + E300 overload (EtherNet/IP)"),
}
NOTES: dict[str, str] = {
    "*": "Overload mounted separately from the contactor, or use the pass-thru version",
    "^": "75 kW and above: kit with separate 5P10-5A current transformers and a 193-1EF*Z overload",
}
#: Number fields: model field -> (title, what it is). Their tag is the title without spaces.
NUMBERS: dict[str, tuple[str, str]] = {
    "fault_ka": ("Fault kA", "rated conditional short-circuit current Iq (kA)"), "kw": ("kW", "motor kW"),
    "flc": ("FLC", "motor full load current @ 400 V (A)"), "cb_amps": ("CB Amps", "circuit breaker rating (A)"),
    "range_min": ("Range Min", "overload setting range from (A)"), "range_max": ("Range Max", "overload setting range to (A)"),
    "inst_trip": ("Inst Trip", "circuit breaker instantaneous trip (A, ±20 %)"),
    "min_trip": ("Min Trip", "minimum trip amps as a multiple of motor FLC"),
    "voltage": ("Voltage", "the voltage the row is for (V); blank: 400"),
}
#: The voltage of a row that doesn't give one: NHP's charts are printed for 400/415 V.
DEFAULT_VOLTAGE = 400.0
TEXTS: dict[str, tuple[str, str]] = {
    "chart": ("Chart", "coordination chart"), "manufacturer": ("Manufacturer", "manufacturer"),
    "cb": ("CB", "circuit breaker"), "el_setting": ("EL Setting", "earth leakage setting range"),
    "contactor": ("Contactor", "contactor"), "overload": ("Overload", "overload relay"), "note": ("Note", "chart note (* or ^)"),
}


class Starter(BaseModel):
    id: str = Field(default_factory=new_id)
    chart: str
    manufacturer: str = ""
    fault_ka: float | None = None
    kw: float
    flc: float | None = None
    cb: str = ""
    cb_amps: float | None = None
    el_setting: str = ""
    contactor: str = ""
    overload: str = ""
    range_min: float | None = None
    range_max: float | None = None
    inst_trip: float | None = None
    min_trip: float | None = None
    #: The voltage the row is for. A load only gets a row of its own voltage range (drives.voltage_class).
    voltage: float = DEFAULT_VOLTAGE
    note: str = ""


class StarterList(BaseModel):
    items: list[Starter] = Field(default_factory=list)
    #: The chart of load types that don't name one.
    default_chart: str = DEFAULT_CHART
    updated_at: datetime | None = None


def _f(text: str) -> float | None:
    t = text.strip()
    return float(t) if t else None


def cb_amps(cb: str) -> float | None:
    """The amps of a circuit breaker as written: "ZS125M / 20A" -> 20."""
    m = re.search(r"(\d+(?:\.\d+)?)\s*A\b", cb.split("/")[-1]) if cb else None
    return float(m.group(1)) if m else None


def default_starters() -> list[Starter]:
    """The starters a project starts with: NHP's six Type 2 charts (ids are stable:
    "nhp-<chart>-<kw>")."""
    out = []
    for line in NHP_TYPE2.strip().splitlines():
        chart, ka, kw, flc, cb, el, con, ol, rng, inst, mult, note, _page = line.split(",")
        lo, hi = (x.strip() for x in rng.split("–"))
        out.append(Starter(id=f"nhp-{chart.lower()}-{kw}", chart=chart, manufacturer="NHP", fault_ka=_f(ka), kw=float(kw),
                           flc=_f(flc), cb=cb, cb_amps=cb_amps(cb), el_setting=el, contactor=con, overload=ol,
                           range_min=_f(lo), range_max=_f(hi), inst_trip=_f(inst), min_trip=_f(mult), note=note))
    return out


def charts_of(items: list[Starter]) -> list[str]:
    """The charts in the list, in order of first appearance."""
    return list(dict.fromkeys(s.chart for s in items))


def check_starters(rows: list[dict], default_chart: str | None = None) -> StarterList:
    """Check the rows as sent: chart and kW required, kW more than 0 and once per chart and
    voltage, the other numbers numbers or blank (CB Amps from the CB when blank; Voltage 400
    when blank, and in one of the voltage ranges). The default chart, when given, must be a
    chart of the list. Order is kept."""
    errors: dict[str, str] = {}
    out: list[Starter] = []
    ids: set[str] = set()
    seen: set[tuple[str, float, float]] = set()
    for raw in rows:
        rid = str(raw.get("id") or new_id())
        if rid in ids:
            raise RefValidationError("Two starters have the same id.", {f"{rid}.chart": "Duplicate item"})
        ids.add(rid)
        data: dict[str, object] = {f: " ".join(str(raw.get(f) if raw.get(f) is not None else "").split()) for f in TEXTS}
        for f in NUMBERS:
            text = str(raw.get(f) if raw.get(f) is not None else "").strip()
            try:
                data[f] = float(text) if text else None
            except ValueError:
                errors[f"{rid}.{f}"] = f"{NUMBERS[f][0]}: not a number"
                data[f] = None
            if isinstance(data[f], float) and data[f] < 0:  # type: ignore[operator]
                errors[f"{rid}.{f}"] = f"{NUMBERS[f][0]}: can't be negative"
        if not data["chart"]:
            errors[f"{rid}.chart"] = "Chart is required"
        if data["voltage"] is None:
            data["voltage"] = DEFAULT_VOLTAGE
        elif voltage_class(data["voltage"]) is None and f"{rid}.voltage" not in errors:
            errors[f"{rid}.voltage"] = f"Voltage: {data['voltage']:g} V is not {VOLTAGE_RANGES}"
        volts = float(data["voltage"])  # type: ignore[arg-type]
        kw = data["kw"]
        if not kw or float(kw) <= 0:  # type: ignore[arg-type]
            errors.setdefault(f"{rid}.kw", "kW is required and more than 0")
            data["kw"] = 0.0
        elif (name_key(str(data["chart"])), volts, float(kw)) in seen:  # type: ignore[arg-type]
            errors[f"{rid}.kw"] = f"{data['chart']} has {kw:g} kW twice" + (f" at {volts:g} V" if volts != DEFAULT_VOLTAGE else "")
        seen.add((name_key(str(data["chart"])), volts, float(data["kw"])))  # type: ignore[arg-type]
        if data["cb_amps"] is None:
            data["cb_amps"] = cb_amps(str(data["cb"]))
        out.append(Starter(id=rid, **data))  # type: ignore[arg-type]
    chart = (default_chart or "").strip()
    if default_chart is not None and chart and name_key(chart) not in {name_key(s.chart) for s in out}:
        errors["default_chart"] = f"'{chart}' is not a chart of the list"
    if errors:
        raise RefValidationError(f"{len(errors)} problem(s) in the starter coordination list.", errors)
    names = {name_key(s.chart): s.chart for s in out}
    return StarterList(items=out, default_chart=names.get(name_key(chart), chart) if chart else "")


# -- matching a load to a starter ---------------------------------------------------------------

def _number(v: object) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        return float(str(v).strip())
    except ValueError:
        return None


def chart_for(load_type_chart: object, default_chart: str) -> str | None:
    """The chart a load type's loads use: its own; blank: the project default; "None": no starter."""
    c = str(load_type_chart or "").strip()
    if c.casefold() == NO_STARTER.casefold():
        return None
    return c or (default_chart or "").strip() or None


def chart_rows(chart: str | None, starters: list[Starter], volts: object = None) -> list[Starter]:
    """The rows of `chart` a load of `volts` can get: those of its voltage range (a 415 V load
    gets the 400 V rows; a 690 V load gets none of them). With no voltage, every row of the chart."""
    if not chart:
        return []
    pool = [s for s in starters if name_key(s.chart) == name_key(chart)]
    if _number(volts) is None:
        return pool
    cls = voltage_class(volts)
    return [s for s in pool if cls is not None and voltage_class(s.voltage) == cls]


def starter_for(rating: object, units: object, chart: str | None, starters: list[Starter], volts: object = None) -> Starter | None:
    """The row of `chart` a load gets, among those of its voltage range (chart_rows): the smallest
    motor kW at least the load's (a rating in Hp converted to kW); a rating in Amps: the smallest
    FLC at least it. None when there is no chart, no rating, no row for its voltage, or the load
    is bigger than the chart."""
    if not chart:
        return None
    r = _number(rating)
    if r is None or r <= 0:
        return None
    pool = chart_rows(chart, starters, volts)
    if unit_kind(units) == "Amps":
        fits = [s for s in pool if s.flc is not None and s.flc >= r - 1e-9]
        return min(fits, key=lambda s: (s.flc, s.kw)) if fits else None
    kw = rating_kw(r, units)
    if kw is None:
        return None
    fits = [s for s in pool if s.kw >= kw - 1e-9]
    return min(fits, key=lambda s: s.kw) if fits else None


def starter_for_load(rating: object, units: object, load_type_chart: object, starters: StarterList | None,
                     volts: object = None) -> Starter | None:
    if starters is None:
        return None
    return starter_for(rating, units, chart_for(load_type_chart, starters.default_chart), starters.items, volts)


def starter_problems(volts: object, load_type_chart: object, starters: StarterList | None, s: Starter | None,
                     motor_flc: object = None, motor_volts: object = None) -> list[str]:
    """What is wrong with a load's starter, in words (nothing: []):
    - its chart has no row for the load's voltage, so it gets no starter;
    - its motor's full load current, at the load's voltage, is outside the overload's setting range."""
    if starters is None:
        return []
    chart = chart_for(load_type_chart, starters.default_chart)
    if not chart:
        return []
    out: list[str] = []
    v = _number(volts)
    of_chart = chart_rows(chart, starters.items)
    if v is not None and of_chart and not chart_rows(chart, starters.items, v):
        made_for = sorted({class_range(voltage_class(x.voltage)) for x in of_chart} - {""})
        out.append(f"No starter is matched: chart {chart} is for {' and '.join(made_for)}, the load is {v:g} V")
    flc = flc_at(motor_flc, motor_volts, volts)
    if s is not None and flc is not None and s.range_min is not None:
        top = s.range_max if s.range_max is not None else s.range_min
        if flc < s.range_min - 1e-9 or flc > top + 1e-9:
            at = f" at {v:g} V" if v is not None else ""
            out.append(f"The motor's full load current ({flc:.3g} A{at}) is outside the overload's setting range "
                       f"({s.range_min:g} to {top:g} A)")
    return out


def starter_fields(s: Starter | None) -> dict[str, object]:
    """A starter's values by tag name (lower case, no spaces): chart, cb, contactor, overload,
    range ("0.2 – 1.0"), elsetting, insttrip, mintrip… Blank when no starter."""
    names = {title.replace(" ", "").casefold(): f for f, (title, _) in {**TEXTS, **NUMBERS}.items()}
    out: dict[str, object] = {k: ("" if s is None or getattr(s, f) is None else getattr(s, f)) for k, f in names.items()}
    out["range"] = "" if s is None or s.range_min is None else f"{s.range_min:g} – {s.range_max:g}" if s.range_max is not None else f"{s.range_min:g}"
    out["description"] = "" if s is None else CHARTS.get(s.chart, (0, ""))[1]
    out["notetext"] = "" if s is None else NOTES.get(s.note, "")
    return out


__all__ = ["Starter", "StarterList", "NUMBERS", "TEXTS", "CHARTS", "NOTES", "DEFAULT_CHART", "NO_STARTER", "default_starters",
           "check_starters", "charts_of", "chart_for", "starter_for", "starter_for_load", "starter_fields", "cb_amps"]
