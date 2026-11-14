# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""The units a load's rating can be in, read the same way everywhere."""

from __future__ import annotations

from typing import Literal

#: One horsepower (mechanical) in kW.
HP_KW = 0.7457
UnitKind = Literal["kW", "HP", "Amps"]


def unit_kind(units: object) -> UnitKind | None:
    """What a load's units text means, ignoring case and spaces: "kW" (blank too), "HP", or
    "Amps" (A, Amp, Amps). None for anything else (kVA, W…): the rating can't be used."""
    u = "" if units is None or isinstance(units, bool) else str(units).strip().casefold()
    if u in ("", "kw"):
        return "kW"
    if u == "hp":
        return "HP"
    if u in ("a", "amp", "amps"):
        return "Amps"
    return None


def rating_kw(rating: float, units: object) -> float | None:
    """A rating as kW: itself in kW, converted from HP; None in Amps or an unknown unit."""
    kind = unit_kind(units)
    return rating if kind == "kW" else rating * HP_KW if kind == "HP" else None
