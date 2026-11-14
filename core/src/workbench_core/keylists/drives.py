# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Drive Data: variable speed drives and their ratings, a flat key list every project starts with
the Rockwell PowerFlex 755TS range in (200-240 V, 380-400 V, 480 V, 575-600 V and 660-690 V, each
in Open, IP54 and Flange enclosures, with their frame sizes; drive_data_755ts).

A load is matched to a drive (`drive_for`) of its voltage class, its **Drive enclosure** (a Load
List field: Open / IP54 / Flange; blank: Open) and its **Drive duty** (ND / HD; blank: Normal
Duty): the smallest whose continuous amps at that duty cover the motor's full load current (the
matched motor's, else a rating in Amps), or, with no current to go on, whose power covers the
load's kW. Template rows and calculated fields reach it as <<Drive.CatNo>>, <<Drive.Frame>>,
<<Drive.Amps>>… (keylists.tag_paths, load_calcs).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from ..refdata.models import RefValidationError, new_id
from ..refdata.validate import name_key
from .drive_data_755ts import PF755TS
from .units import HP_KW, rating_kw, unit_kind

Enclosure = Literal["Open", "IP54", "Flange"]
ENCLOSURES: dict[str, str] = {"Open": "IP00/IP20, NEMA/UL Type Open", "IP54": "IP54, NEMA/UL Type 12",
                              "Flange": "Flange Mount (front: IP20, NEMA/UL Type Open; back/heatsink: IP66, NEMA/UL Type 4X)"}
RANGES: dict[int, str] = {240: "200…240V", 400: "380…400V", 480: "480V", 600: "575…600V", 690: "660…690V"}
#: Number fields: model field -> (title, what it is). Their tag is the title without spaces.
NUMBERS: dict[str, tuple[str, str]] = {
    "nd_amps": ("ND Amps", "Normal Duty continuous output amps"), "nd_amps_1min": ("ND 1min", "Normal Duty 1 min output amps"),
    "nd_amps_3s": ("ND 3s", "Normal Duty 3 s output amps"), "nd_kw": ("ND kW", "Normal Duty power (kW)"),
    "nd_hp": ("ND Hp", "Normal Duty power (Hp)"),
    "hd_amps": ("HD Amps", "Heavy Duty continuous output amps"), "hd_amps_1min": ("HD 1min", "Heavy Duty 1 min output amps"),
    "hd_amps_3s": ("HD 3s", "Heavy Duty 3 s output amps"), "hd_kw": ("HD kW", "Heavy Duty power (kW)"),
    "hd_hp": ("HD Hp", "Heavy Duty power (Hp)"),
    "nd_amps_208": ("ND Amps 208", "Normal Duty continuous amps at 208 V (200-240 V drives)"),
    "nd_amps_1min_208": ("ND 1min 208", "Normal Duty 1 min amps at 208 V"), "nd_amps_3s_208": ("ND 3s 208", "Normal Duty 3 s amps at 208 V"),
    "hd_amps_208": ("HD Amps 208", "Heavy Duty continuous amps at 208 V"), "hd_amps_1min_208": ("HD 1min 208", "Heavy Duty 1 min amps at 208 V"),
    "hd_amps_3s_208": ("HD 3s 208", "Heavy Duty 3 s amps at 208 V"),
}
TEXTS: dict[str, tuple[str, str]] = {
    "cat_no": ("Cat No", "catalog number"), "manufacturer": ("Manufacturer", "manufacturer"), "series": ("Series", "range"),
    "enclosure": ("Enclosure", "Open, IP54 or Flange"), "frame": ("Frame", "frame size"),
}


class Drive(BaseModel):
    id: str = Field(default_factory=new_id)
    cat_no: str
    manufacturer: str = ""
    series: str = ""
    voltage: int  # the voltage class: 240, 400, 480, 600 or 690
    enclosure: Enclosure = "Open"
    frame: str = ""
    nd_amps: float
    nd_amps_1min: float | None = None
    nd_amps_3s: float | None = None
    nd_kw: float | None = None
    nd_hp: float | None = None
    hd_amps: float | None = None
    hd_amps_1min: float | None = None
    hd_amps_3s: float | None = None
    hd_kw: float | None = None
    hd_hp: float | None = None
    nd_amps_208: float | None = None
    nd_amps_1min_208: float | None = None
    nd_amps_3s_208: float | None = None
    hd_amps_208: float | None = None
    hd_amps_1min_208: float | None = None
    hd_amps_3s_208: float | None = None


class DriveList(BaseModel):
    items: list[Drive] = Field(default_factory=list)
    updated_at: datetime | None = None


def _f(text: str) -> float | None:
    t = text.strip().rstrip(".")
    return float(t) if t else None


def default_drives() -> list[Drive]:
    """The drives a project starts with: PowerFlex 755TS (ids are stable: "755ts-<voltage>-<cat no>")."""
    out = []
    for line in PF755TS.strip().splitlines():
        v, enc, frame, cat, *rest = line.split(",")
        nd, hd, low = rest[0:4], rest[4:8], rest[8:16]
        volts = int(v)
        power = "hp" if volts in (240, 480, 600) else "kw"
        d = {"nd_amps": _f(nd[0]), "nd_amps_1min": _f(nd[1]), "nd_amps_3s": _f(nd[2]), f"nd_{power}": _f(nd[3]),
             "hd_amps": _f(hd[0]), "hd_amps_1min": _f(hd[1]), "hd_amps_3s": _f(hd[2]), f"hd_{power}": _f(hd[3])}
        if volts == 240 and any(low):  # the figures in parentheses: 208 V amps; the kW of the Hp
            d |= {"nd_amps_208": _f(low[0]), "nd_amps_1min_208": _f(low[1]), "nd_amps_3s_208": _f(low[2]), "nd_kw": _f(low[3]),
                  "hd_amps_208": _f(low[4]), "hd_amps_1min_208": _f(low[5]), "hd_amps_3s_208": _f(low[6]), "hd_kw": _f(low[7])}
        out.append(Drive(id=f"755ts-{volts}-{cat.lower()}", cat_no=cat, manufacturer="Rockwell Automation",
                         series="PowerFlex 755TS", voltage=volts, enclosure=enc, frame=frame, **d))
    return out


def check_drives(rows: list[dict]) -> list[Drive]:
    """Check the rows as sent: catalog number required, and unique within its voltage class
    (frame 6 and 7 drives are listed at both 600 V and 690 V); voltage class one of RANGES;
    enclosure Open, IP54 or Flange; ND continuous amps a positive number; the other numbers
    numbers or blank. Order is kept."""
    errors: dict[str, str] = {}
    out: list[Drive] = []
    ids: set[str] = set()
    seen: set[tuple[str, int]] = set()
    for raw in rows:
        rid = str(raw.get("id") or new_id())
        if rid in ids:
            raise RefValidationError("Two drives have the same id.", {f"{rid}.cat_no": "Duplicate item"})
        ids.add(rid)
        data: dict[str, object] = {f: str(raw.get(f) if raw.get(f) is not None else "").strip() for f in TEXTS}
        try:
            volts = int(float(str(raw.get("voltage")).strip()))
            if volts not in RANGES:
                raise ValueError
        except (ValueError, TypeError):
            errors[f"{rid}.voltage"] = f"Voltage class: one of {', '.join(str(v) for v in RANGES)}"
            volts = 400
        data["voltage"] = volts
        if not data["cat_no"]:
            errors[f"{rid}.cat_no"] = "Catalog number is required"
        elif (name_key(str(data["cat_no"])), volts) in seen:
            errors[f"{rid}.cat_no"] = f"'{data['cat_no']}' is in the {volts} V drives twice"
        seen.add((name_key(str(data["cat_no"])), volts))
        enc = str(data["enclosure"])
        data["enclosure"] = next((e for e in ENCLOSURES if e.casefold() == enc.casefold()), None) or _enclosure(enc)
        for f in NUMBERS:
            text = str(raw.get(f) if raw.get(f) is not None else "").strip()
            try:
                data[f] = float(text) if text else None
            except ValueError:
                errors[f"{rid}.{f}"] = f"{NUMBERS[f][0]}: not a number"
                data[f] = None
        if not data["nd_amps"] or float(data["nd_amps"]) <= 0:  # type: ignore[arg-type]
            errors.setdefault(f"{rid}.nd_amps", "ND Amps is required and more than 0")
            data["nd_amps"] = 0.0
        out.append(Drive(id=rid, **data))  # type: ignore[arg-type]
    if errors:
        raise RefValidationError(f"{len(errors)} problem(s) in the drive data.", errors)
    return out


# -- matching a load to a drive -----------------------------------------------------------------

def _number(v: object) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        return float(str(v).strip())
    except ValueError:
        return None


#: The voltage classes: (from, to, class), both ends included.
VOLTAGE_CLASSES: tuple[tuple[int, int, int], ...] = ((200, 240, 240), (380, 415, 400), (440, 480, 480), (550, 600, 600), (660, 690, 690))


def voltage_class(volts: object) -> int | None:
    """The voltage class of a voltage: 200-240 -> 240, 380-415 -> 400, 440-480 -> 480,
    550-600 -> 600, 660-690 -> 690. None for a voltage in none of them."""
    v = _number(volts)
    if v is None:
        return None
    for lo, hi, cls in VOLTAGE_CLASSES:
        if lo <= v <= hi:
            return cls
    return None


def class_range(cls: int | None) -> str:
    """A voltage class in words: 400 -> "380-415 V"."""
    return next((f"{lo}-{hi} V" for lo, hi, c in VOLTAGE_CLASSES if c == cls), "")


#: The voltage ranges a drive can be matched in, for messages.
VOLTAGE_RANGES = "200-240, 380-415, 440-480, 550-600 or 660-690 V"


def flc_at(motor_flc: object, motor_volts: object, load_volts: object) -> float | None:
    """A motor's full load current at the load's voltage. The Motor Data figure is at the
    motor's own rated voltage (415 V for the WEG table); for the same power the current
    changes inversely with the voltage: 55.4 A at 415 V is 95.8 A at 240 V and 33.3 A at 690 V.
    Unchanged when either voltage isn't known."""
    flc, mv, lv = _number(motor_flc), _number(motor_volts), _number(load_volts)
    if flc is None or mv is None or lv is None or mv <= 0 or lv <= 0:
        return flc
    return flc * mv / lv


def _enclosure(text: object) -> Enclosure:
    t = str(text or "").casefold()
    if "flange" in t:
        return "Flange"
    if "54" in t or "type 12" in t or t.strip() in ("12", "nema 12"):
        return "IP54"
    return "Open"


def duty_of(text: object) -> str:
    """"HD" for a heavy duty load (HD, Heavy…), else "ND"."""
    return "HD" if str(text or "").strip().casefold().startswith("h") else "ND"


def _frame_order(frame: str) -> tuple[int, str]:
    digits = "".join(ch for ch in frame if ch.isdigit())
    return (int(digits) if digits else 99, frame)


def drive_for(volts: object, amps: object, kw: object, duty: object, enclosure: object, drives: list[Drive]) -> Drive | None:
    """The drive a load gets: of its voltage class and enclosure, the smallest whose continuous
    amps at its duty (at 208 V for a 200-220 V load) are at least `amps`; with no amps, the
    smallest whose power at that duty is at least `kw`; the smaller frame of two the same. None
    when nothing fits."""
    cls = voltage_class(volts)
    if cls is None:
        return None
    d = duty_of(duty).lower()
    enc = _enclosure(enclosure)
    low = cls == 240 and (_number(volts) or 240) < 220
    pool = [x for x in drives if x.voltage == cls and x.enclosure == enc]
    a = _number(amps)
    if a is not None and a > 0:
        def rated(x: Drive) -> float | None:
            return getattr(x, f"{d}_amps_208") if low and getattr(x, f"{d}_amps_208") is not None else getattr(x, f"{d}_amps")
        fits = [x for x in pool if (rated(x) or 0) >= a - 1e-9]
        return min(fits, key=lambda x: (rated(x) or 0, _frame_order(x.frame), x.cat_no)) if fits else None
    k = _number(kw)
    if k is None or k <= 0:
        return None

    def power(x: Drive) -> float:
        kw_ = getattr(x, f"{d}_kw")
        hp = getattr(x, f"{d}_hp")
        return kw_ if kw_ is not None else (hp * HP_KW if hp is not None else 0)
    fits = [x for x in pool if power(x) >= k - 1e-9]
    return min(fits, key=lambda x: (power(x), x.nd_amps, _frame_order(x.frame), x.cat_no)) if fits else None


def drive_for_load(rating: object, units: object, volts: object, motor_flc: object, duty: object, enclosure: object,
                   drives: list[Drive]) -> Drive | None:
    """A load's drive: matched on its motor's full load current (`motor_flc`), else a rating in
    Amps; with neither, on its power (a rating in kW, or Hp converted)."""
    r = _number(rating)
    amps = _number(motor_flc)
    if amps is None and unit_kind(units) == "Amps" and r is not None:
        amps = r
    kw = None if r is None else rating_kw(r, units)
    return drive_for(volts, amps, kw, duty, enclosure, drives)


def drive_fields(x: Drive | None, duty: object = "") -> dict[str, object]:
    """A drive's values by tag name (lower case, no spaces): catno, frame, amps (continuous at the
    load's duty), amps1min, amps3s, kw, hp, duty, and every ND/HD figure. Blank when no drive."""
    d = duty_of(duty).lower()
    names = {"catno": "cat_no", "manufacturer": "manufacturer", "series": "series", "enclosure": "enclosure", "frame": "frame",
             "voltage": "voltage"}
    names |= {title.replace(" ", "").casefold(): f for f, (title, _) in NUMBERS.items()}
    out: dict[str, object] = {k: ("" if x is None else getattr(x, f)) for k, f in names.items()}
    at_duty = {"amps": f"{d}_amps", "amps1min": f"{d}_amps_1min", "amps3s": f"{d}_amps_3s", "kw": f"{d}_kw", "hp": f"{d}_hp"}
    out |= {k: ("" if x is None or getattr(x, f) is None else getattr(x, f)) for k, f in at_duty.items()}
    out["duty"] = "" if x is None else d.upper()
    out["voltagerange"] = "" if x is None else RANGES.get(x.voltage, "")
    return {k: ("" if v is None else v) for k, v in out.items()}


__all__ = ["Drive", "DriveList", "NUMBERS", "TEXTS", "ENCLOSURES", "RANGES", "default_drives", "check_drives", "drive_for",
           "drive_for_load",
           "drive_fields", "voltage_class", "duty_of"]
