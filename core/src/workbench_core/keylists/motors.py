# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Motor Data: a flat key list of motors and their performance data, which every project starts
with the WEG W22 High Efficiency E3 range in (2, 4, 6 and 8 pole, 415 V 50 Hz; motor_data_w22).

A load is matched to a motor by its rating and poles (`motor_for`): the smallest motor with
those poles whose output is at least the load's kW (a rating in HP is converted), a Standard
design before a High-Output one of the same output. Template rows and calculated fields reach
it as <<Motor.PartNo>>, <<Motor.FLC>>, <<Motor.Eff100>>… (keylists.tag_paths, load_calcs).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from ..refdata.models import RefValidationError, new_id
from ..refdata.validate import name_key
from .motor_data_w22 import W22_E3_415V_50HZ

HP_KW = 0.7457
#: Number fields: model field -> (column title, what it is). Their tag is the title without spaces.
NUMBERS: dict[str, tuple[str, str]] = {
    "kw": ("kW", "output (kW)"), "speed": ("Speed", "rated speed (rpm)"), "flc": ("FLC", "full load current (A)"),
    "il_ir": ("IL/Ir", "locked rotor current (x FLC)"), "torque": ("Torque", "full load torque (Nm)"),
    "tl_tr": ("TL/Tr", "locked rotor torque (x full load)"), "tb_tr": ("Tb/Tr", "breakdown torque (x full load)"),
    "eff50": ("Eff50", "efficiency at 50 % load (%)"), "eff75": ("Eff75", "efficiency at 75 % load (%)"),
    "eff100": ("Eff100", "efficiency at full load (%)"), "pf50": ("PF50", "power factor at 50 % load"),
    "pf75": ("PF75", "power factor at 75 % load"), "pf100": ("PF100", "power factor at full load"),
    "sound": ("Sound", "sound pressure level (dB(A))"), "inertia": ("Inertia", "moment of inertia (kgm²)"),
    "locked_cold": ("Locked Cold", "max. locked rotor time, cold (s)"), "locked_hot": ("Locked Hot", "max. locked rotor time, hot (s)"),
    "weight": ("Weight", "approximate weight (kg)"), "voltage": ("Voltage", "rated voltage (V)"), "frequency": ("Hz", "frequency (Hz)"),
}
TEXTS: dict[str, tuple[str, str]] = {
    "part_no": ("Part No", "part number"), "manufacturer": ("Manufacturer", "manufacturer"), "series": ("Series", "range"),
    "design": ("Design", "Standard or High-Output (special frame)"), "frame": ("Frame", "IEC frame"),
}
Design = Literal["Standard", "High-Output"]


class Motor(BaseModel):
    id: str = Field(default_factory=new_id)
    part_no: str
    manufacturer: str = ""
    series: str = ""
    poles: int
    design: Design = "Standard"
    frame: str = ""
    reduced_frame: bool = False  # the output in a smaller frame than usual (High-Output, *)
    kw: float
    speed: float | None = None
    flc: float | None = None
    il_ir: float | None = None
    torque: float | None = None
    tl_tr: float | None = None
    tb_tr: float | None = None
    eff50: float | None = None
    eff75: float | None = None
    eff100: float | None = None
    pf50: float | None = None
    pf75: float | None = None
    pf100: float | None = None
    sound: float | None = None
    inertia: float | None = None
    locked_cold: float | None = None
    locked_hot: float | None = None
    weight: float | None = None
    voltage: float | None = None
    frequency: float | None = None


class MotorList(BaseModel):
    items: list[Motor] = Field(default_factory=list)
    updated_at: datetime | None = None


_W22_COLUMNS = ["part_no", "poles", "design", "kw", "frame", "speed", "flc", "il_ir", "torque", "tl_tr", "tb_tr",
                "eff50", "eff75", "eff100", "pf50", "pf75", "pf100", "sound", "inertia", "locked_cold", "locked_hot", "weight"]


def default_motors() -> list[Motor]:
    """The motors a project starts with: WEG W22 E3, 415 V 50 Hz (ids are stable: "w22-<part>")."""
    out = []
    for line in W22_E3_415V_50HZ.strip().splitlines():
        raw = dict(zip(_W22_COLUMNS, line.split(",")))
        frame = raw.pop("frame")
        mid = "w22-" + "".join(ch if ch.isalnum() else "-" for ch in raw["part_no"].replace(" W22", "")).lower()
        out.append(Motor(id=mid, manufacturer="WEG", series="W22 IE3 High Efficiency", frame=frame.rstrip("*"),
                         reduced_frame=frame.endswith("*"), voltage=415, frequency=50, **raw))
    return out


def check_motors(rows: list[dict]) -> list[Motor]:
    """Check the rows as sent: part number required and unique (ignoring case and extra spaces),
    poles a whole number from 2 to 16 and kW a positive number, the other numbers numbers or
    blank. Order is kept."""
    errors: dict[str, str] = {}
    out: list[Motor] = []
    ids: set[str] = set()
    parts: set[str] = set()
    for raw in rows:
        rid = str(raw.get("id") or new_id())
        if rid in ids:
            raise RefValidationError("Two motors have the same id.", {f"{rid}.part_no": "Duplicate item"})
        ids.add(rid)
        data: dict[str, object] = {f: str(raw.get(f) if raw.get(f) is not None else "").strip() for f in TEXTS}
        if not data["part_no"]:
            errors[f"{rid}.part_no"] = "Part number is required"
        elif name_key(str(data["part_no"])) in parts:
            errors[f"{rid}.part_no"] = f"Part number '{data['part_no']}' is used twice"
        parts.add(name_key(str(data["part_no"])))
        if data["design"] not in ("Standard", "High-Output"):
            data["design"] = "High-Output" if str(data["design"]).casefold().startswith("high") else "Standard"
        flag = str(raw.get("reduced_frame") if raw.get("reduced_frame") is not None else "").strip().casefold()
        data["reduced_frame"] = flag in ("true", "yes", "y", "1", "x")
        try:
            poles = int(float(str(raw.get("poles")).strip()))
            if not 2 <= poles <= 16 or poles % 2:
                raise ValueError
            data["poles"] = poles
        except (ValueError, TypeError):
            errors[f"{rid}.poles"] = "Poles: an even whole number, 2 to 16"
            data["poles"] = 2
        for f in NUMBERS:
            text = str(raw.get(f) if raw.get(f) is not None else "").strip()
            try:
                data[f] = float(text) if text else None
            except ValueError:
                errors[f"{rid}.{f}"] = f"{NUMBERS[f][0]}: not a number"
                data[f] = None
        if not data["kw"] or float(data["kw"]) <= 0:  # type: ignore[arg-type]
            errors.setdefault(f"{rid}.kw", "kW is required and more than 0")
            data["kw"] = 0.0
        out.append(Motor(id=rid, **data))  # type: ignore[arg-type]
    if errors:
        raise RefValidationError(f"{len(errors)} problem(s) in the motor data.", errors)
    return out


def _number(v: object) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        return float(str(v).strip())
    except ValueError:
        return None


def motor_for(rating: object, units: object, poles: object, motors: list[Motor]) -> Motor | None:
    """The motor a load gets: the smallest of `poles` whose output is at least the load's kW (a
    rating in HP converted; one in Amps or blank matches nothing), Standard design before
    High-Output. None when no motor fits."""
    kw, p = _number(rating), _number(poles)
    if kw is None or kw <= 0 or p is None:
        return None
    u = str(units or "kW").strip().casefold()
    if u in ("hp",):
        kw *= HP_KW
    elif u not in ("kw", ""):
        return None
    fits = [m for m in motors if m.poles == int(p) and m.kw >= kw - 1e-9]
    if not fits:
        return None
    return min(fits, key=lambda m: (m.kw, m.design != "Standard", m.part_no))


def motor_fields(m: Motor | None) -> dict[str, object]:
    """A motor's values by tag name (lower case, no spaces): partno, kw, flc, eff100… Blank when no motor."""
    names = {"partno": "part_no", "manufacturer": "manufacturer", "series": "series", "design": "design", "frame": "frame",
             "poles": "poles", "reducedframe": "reduced_frame"}
    names |= {title.replace(" ", "").replace("/", "").casefold(): f for f, (title, _) in NUMBERS.items()}
    names |= {f.replace("_", ""): f for f in NUMBERS}
    return {k: ("" if m is None else getattr(m, f)) for k, f in names.items()}


__all__ = ["Motor", "MotorList", "NUMBERS", "TEXTS", "default_motors", "check_motors", "motor_for", "motor_fields"]
