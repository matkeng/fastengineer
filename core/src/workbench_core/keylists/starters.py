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
}
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
    """Check the rows as sent: chart and kW required, kW more than 0 and once per chart, the
    other numbers numbers or blank (CB Amps from the CB when blank). The default chart, when
    given, must be a chart of the list. Order is kept."""
    errors: dict[str, str] = {}
    out: list[Starter] = []
    ids: set[str] = set()
    seen: set[tuple[str, float]] = set()
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
        kw = data["kw"]
        if not kw or float(kw) <= 0:  # type: ignore[arg-type]
            errors.setdefault(f"{rid}.kw", "kW is required and more than 0")
            data["kw"] = 0.0
        elif (name_key(str(data["chart"])), float(kw)) in seen:  # type: ignore[arg-type]
            errors[f"{rid}.kw"] = f"{data['chart']} has {kw:g} kW twice"
        seen.add((name_key(str(data["chart"])), float(data["kw"])))  # type: ignore[arg-type]
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


def starter_for(rating: object, units: object, chart: str | None, starters: list[Starter]) -> Starter | None:
    """The row of `chart` a load gets: the smallest motor kW at least the load's (a rating in Hp
    converted to kW); a rating in Amps: the smallest FLC at least it. None when there is no chart,
    no rating, or the load is bigger than the chart."""
    if not chart:
        return None
    r = _number(rating)
    if r is None or r <= 0:
        return None
    pool = [s for s in starters if name_key(s.chart) == name_key(chart)]
    if unit_kind(units) == "Amps":
        fits = [s for s in pool if s.flc is not None and s.flc >= r - 1e-9]
        return min(fits, key=lambda s: (s.flc, s.kw)) if fits else None
    kw = rating_kw(r, units)
    if kw is None:
        return None
    fits = [s for s in pool if s.kw >= kw - 1e-9]
    return min(fits, key=lambda s: s.kw) if fits else None


def starter_for_load(rating: object, units: object, load_type_chart: object, starters: StarterList | None) -> Starter | None:
    if starters is None:
        return None
    return starter_for(rating, units, chart_for(load_type_chart, starters.default_chart), starters.items)


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
