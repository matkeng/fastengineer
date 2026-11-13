# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Load Factors: load and demand factors by equipment type, a flat key list every project starts
with (the plant's typical factors: plant nameplate and plant optimised load factors, average and
maximum demand factors), plus a **Default** row.

A load is matched on its **Equipment type** (a Load List field, e.g. from the MEL): the row of
the same name, ignoring case and extra spaces; a type that isn't listed gets the Default row.
Template rows, calculated fields and the summary page reach it as <<LoadFactor.NameplateLF>>,
<<LoadFactor.OptimisedLF>>, <<LoadFactor.AvgDemand>>, <<LoadFactor.MaxDemand>>…
(keylists.tag_paths, load_calcs).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from ..refdata.models import RefValidationError, new_id
from ..refdata.validate import name_key

DEFAULT_NAME = "Default"
#: Equipment type, plant nameplate load factor, plant optimised load factor, average demand factor,
#: max demand factor: the table a project starts with.
DEFAULT_ROWS: tuple[tuple[str, float, float, float, float], ...] = (
    (DEFAULT_NAME, 0.75, 0.95, 1.00, 1.00),
    ("Absorber", 0.75, 0.95, 1.00, 1.00), ("Agitator", 0.75, 0.95, 1.00, 1.00), ("Air Blaster", 0.75, 0.95, 1.00, 1.00),
    ("Air Conditioner", 0.75, 0.95, 0.50, 1.00), ("Apron Feeders", 0.75, 0.95, 1.00, 1.00), ("Auxiliaries", 0.75, 0.95, 1.00, 1.00),
    ("Baghouse", 0.75, 0.95, 1.00, 1.00), ("Ball Charger", 0.75, 0.95, 0.10, 1.00), ("Belt Feeders", 0.75, 0.95, 1.00, 1.00),
    ("Belt Filters", 0.75, 0.95, 1.00, 1.00), ("Bin Activator", 0.75, 0.95, 1.00, 1.00), ("Blower", 0.75, 0.95, 1.00, 1.00),
    ("Boiler", 0.75, 0.95, 0.25, 1.00), ("Carbon Regen Kiln", 0.75, 0.95, 0.83, 1.00), ("Cell", 0.75, 0.95, 1.00, 1.00),
    ("Centrifuge", 0.75, 0.95, 1.00, 1.00), ("Chiller", 0.75, 0.95, 1.00, 1.00), ("Clarifier", 0.75, 0.95, 1.00, 1.00),
    ("Classifier", 0.75, 0.95, 1.00, 1.00), ("Column", 0.75, 0.95, 1.00, 1.00), ("Compressor", 0.75, 0.95, 0.50, 1.00),
    ("Concentrator", 0.75, 0.95, 1.00, 1.00), ("Conveyor", 0.75, 0.95, 1.00, 1.00), ("Cooling Tower", 0.75, 0.95, 1.00, 1.00),
    ("Crane/Hoist", 0.75, 0.95, 0.05, 0.50), ("Crusher", 0.75, 0.95, 1.00, 1.00), ("Crystallizer", 0.75, 0.95, 1.00, 1.00),
    ("Cyclone", 0.75, 0.95, 1.00, 1.00), ("Davit", 0.75, 0.95, 0.05, 1.00), ("Distributor", 0.75, 0.95, 1.00, 1.00),
)
#: Number fields: model field -> (title, what it is). Their tag is the title without spaces.
NUMBERS: dict[str, tuple[str, str]] = {
    "nameplate_lf": ("Nameplate LF", "plant nameplate load factor"),
    "optimised_lf": ("Optimised LF", "plant optimised load factor"),
    "avg_demand": ("Avg Demand", "average demand factor"),
    "max_demand": ("Max Demand", "maximum demand factor"),
}
TEXTS: dict[str, tuple[str, str]] = {"equipment_type": ("Equipment Type", "equipment type"), "notes": ("Notes", "notes")}
MAX_FACTOR = 10.0


class LoadFactor(BaseModel):
    id: str = Field(default_factory=new_id)
    equipment_type: str
    nameplate_lf: float | None = None
    optimised_lf: float | None = None
    avg_demand: float | None = None
    max_demand: float | None = None
    notes: str = ""


class LoadFactorList(BaseModel):
    items: list[LoadFactor] = Field(default_factory=list)
    updated_at: datetime | None = None


def _id(name: str) -> str:
    return "lf-" + name_key(name).replace(" ", "-").replace("/", "-")


def default_load_factors() -> list[LoadFactor]:
    """The rows a project starts with (ids are stable: "lf-<equipment type>")."""
    return [LoadFactor(id=_id(n), equipment_type=n, nameplate_lf=a, optimised_lf=b, avg_demand=c, max_demand=d)
            for n, a, b, c, d in DEFAULT_ROWS]


def check_load_factors(rows: list[dict]) -> list[LoadFactor]:
    """Check the rows as sent: equipment type required and unique (ignoring case and extra
    spaces); each factor a number from 0 to 10, or blank. Order is kept."""
    errors: dict[str, str] = {}
    out: list[LoadFactor] = []
    ids: set[str] = set()
    seen: set[str] = set()
    for raw in rows:
        rid = str(raw.get("id") or new_id())
        if rid in ids:
            raise RefValidationError("Two load factor rows have the same id.", {f"{rid}.equipment_type": "Duplicate item"})
        ids.add(rid)
        data: dict[str, object] = {f: " ".join(str(raw.get(f) if raw.get(f) is not None else "").split()) for f in TEXTS}
        name = str(data["equipment_type"])
        if not name:
            errors[f"{rid}.equipment_type"] = "Equipment type is required"
        elif name_key(name) in seen:
            errors[f"{rid}.equipment_type"] = f"'{name}' is in the list twice"
        seen.add(name_key(name))
        for f in NUMBERS:
            text = str(raw.get(f) if raw.get(f) is not None else "").strip()
            try:
                data[f] = float(text) if text else None
            except ValueError:
                errors[f"{rid}.{f}"] = f"{NUMBERS[f][0]}: not a number"
                data[f] = None
                continue
            if data[f] is not None and not 0 <= float(data[f]) <= MAX_FACTOR:  # type: ignore[arg-type]
                errors[f"{rid}.{f}"] = f"{NUMBERS[f][0]}: from 0 to {MAX_FACTOR:g}"
        out.append(LoadFactor(id=rid, **data))  # type: ignore[arg-type]
    if errors:
        raise RefValidationError(f"{len(errors)} problem(s) in the load factors.", errors)
    return out


def load_factor_for(equipment_type: object, rows: list[LoadFactor]) -> tuple[LoadFactor | None, bool]:
    """The row a load's equipment type gets, and whether it is the type's own row: the row of
    that name (ignoring case and extra spaces), else the Default row (False), else (None, False)."""
    key = name_key(str(equipment_type or ""))
    by_name = {name_key(r.equipment_type): r for r in rows}
    if key and key in by_name and key != name_key(DEFAULT_NAME):
        return by_name[key], True
    return by_name.get(name_key(DEFAULT_NAME)), False


def load_factor_fields(row: LoadFactor | None, matched: bool = True) -> dict[str, object]:
    """A row's values by tag name (lower case, no spaces): equipmenttype, nameplatelf, optimisedlf,
    avgdemand, maxdemand, notes, and matched (True when the load's type has its own row, False
    when it got the Default row). Blank when no row."""
    names = {title.replace(" ", "").casefold(): f for f, (title, _) in {**TEXTS, **NUMBERS}.items()}
    out: dict[str, object] = {k: ("" if row is None or getattr(row, f) is None else getattr(row, f)) for k, f in names.items()}
    out["matched"] = "" if row is None else matched
    return out


__all__ = ["LoadFactor", "LoadFactorList", "NUMBERS", "TEXTS", "DEFAULT_NAME", "DEFAULT_ROWS", "default_load_factors",
           "check_load_factors", "load_factor_for", "load_factor_fields"]
