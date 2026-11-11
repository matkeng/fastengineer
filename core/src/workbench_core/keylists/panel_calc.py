# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""The arithmetic of a distribution panel schedule (no project data in here).

Every pole row of the schedule carries watts (quantity x watts each) on one phase. From
those, with the panel's single-phase voltage, one power factor for the whole panel and the
rating of its isolator and chassis:

    phase kVA      = phase W / power factor / 1000
    phase amps     = phase kVA x 1000 / voltage
    Maximum Amp    = the largest phase amps
    kW             = all the watts / 1000
    Remaining (A)  = rating - Maximum Amp        Remaining % = Remaining / rating x 100
    Maximum kVA    = 3 x voltage x rating / 1000 (three-phase); voltage x rating / 1000 (single)

A missing or zero voltage, power factor or rating gives zeros, never an error.
"""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel

#: The phases of a three-phase panel, in the order of its pole rows: red, white, blue.
POLES: tuple[str, ...] = ("R", "W", "B")


class PanelTotals(BaseModel):
    phases: list[str]  # ["R", "W", "B"], or [""] for a single-phase panel
    phase_w: list[float]
    phase_kva: list[float]
    phase_amps: list[float]
    max_amps: float = 0
    total_kw: float = 0
    remaining_amps: float = 0
    remaining_pct: float | None = None  # None when there is no rating
    max_kva: float = 0


def default_pole_watts(rating: float | None, unit: str, poles: int, voltage: float, power_factor: float) -> float | None:
    """The watts on each pole of a load, from its rating: a kW rating is shared equally by its
    poles; an Amps rating is the current in each pole. None when the load has no rating."""
    if rating is None or poles < 1:
        return None
    if unit.strip().casefold() == "amps":
        return rating * voltage * power_factor
    return rating * 1000 / poles


def panel_totals(pole_watts: Iterable[tuple[str, float]], *, three_phase: bool, voltage: float, power_factor: float,
                 isolator_rating: float) -> PanelTotals:
    """`pole_watts`: (phase, watts) for each pole row. On a single-phase panel the phase is ignored."""
    phases = list(POLES) if three_phase else [""]
    watts = dict.fromkeys(phases, 0.0)
    for phase, w in pole_watts:
        key = phase if three_phase else ""
        if key in watts:
            watts[key] += w
    kva = [w / power_factor / 1000 if power_factor > 0 else 0.0 for w in watts.values()]
    amps = [k * 1000 / voltage if voltage > 0 else 0.0 for k in kva]
    rating = max(isolator_rating, 0)
    remaining = rating - max(amps)
    return PanelTotals(
        phases=phases, phase_w=list(watts.values()), phase_kva=kva, phase_amps=amps, max_amps=max(amps),
        total_kw=sum(watts.values()) / 1000, remaining_amps=remaining,
        remaining_pct=remaining / rating * 100 if rating > 0 else None,
        max_kva=(3 if three_phase else 1) * max(voltage, 0) * rating / 1000)
