# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Board loading: the demand below each board against its rating (keylists.loading)."""

from __future__ import annotations

import math

import pytest

from workbench_core.keylists.load_factors import default_load_factors
from workbench_core.keylists.loading import board_loading, load_demand
from workbench_core.keylists.loadlist import LoadListRow
from workbench_core.keylists.motors import default_motors

FACTORS = default_load_factors()  # the Default row: nameplate 0.75, average 1, maximum 1


def _load(tag: str, rating=None, fed="", units="", volts=415, **more) -> LoadListRow:
    more.setdefault("supplied_from", f"m/{fed}" if fed else None)
    return LoadListRow(recipe_id="m", key=tag, source="MEL", target="MEL",
                       values={"tag": tag, "load_rating": rating, "load_units": units, "load_voltage": volts}, **more)


LOADS = [
    _load("MSB", is_panel=True, supplied_from="primary"),
    _load("TX-1", 1000, "MSB", "kVA", is_panel=True),
    _load("MCC-1", 400, "TX-1", "A", is_panel=True), _load("MCC-2", None, "TX-1", is_panel=True),
    _load("P-1", 75, "MCC-1"), _load("P-2", 40, "MCC-1", "HP"), _load("N-1", None, "MCC-1"),
    _load("F-1", 20, "MCC-2", "Amps"), _load("U-1", 2, "MCC-2", "MW"),
    _load("H-1", 9, "MSB"), _load("X-1", 500, "MCC-1", status="deleted"),
]


def test_a_loads_demand() -> None:
    d = load_demand({"rating": 75, "units": "kW", "loadfactor.nameplatelf": 0.75, "loadfactor.maxdemand": 1, "loadfactor.avgdemand": 0.5})
    assert (d.connected_kw, d.max_kw, d.avg_kw) == (75, 56.25, 28.125) and d.max_kva == pytest.approx(56.25 / 0.85)
    # its motor's power factor when it has one; HP converted; Amps and kVA through the voltage and power factor
    assert load_demand({"rating": 75, "motor.pf100": 0.9}).max_kva == pytest.approx(75 / 0.9)
    assert load_demand({"rating": 100, "units": "hp"}).connected_kw == pytest.approx(74.57)
    amps = load_demand({"rating": 20, "units": "A", "voltage": 415, "phases": "AC-3-phase"})
    assert amps.max_kva == pytest.approx(math.sqrt(3) * 415 * 20 / 1000) and amps.connected_kw == pytest.approx(amps.max_kva * 0.85)
    assert load_demand({"rating": 20, "units": "A", "voltage": 240, "phases": "AC-1-phase-LN"}).max_kva == pytest.approx(4.8)
    assert load_demand({"rating": 20, "units": "A", "voltage": 24, "phases": "DC"}).connected_kw == pytest.approx(0.48)
    assert load_demand({"rating": 50, "units": "kVA"}).connected_kw == pytest.approx(42.5)
    # what can't be counted says why
    assert load_demand({"rating": ""}).left_out == "No rating"
    assert load_demand({"rating": 2, "units": "MW"}).left_out == "Its units (MW) are not kW, HP, Amps or kVA"
    assert load_demand({"rating": 20, "units": "A"}).left_out == "Rated in Amps with no voltage"


def test_boards_total_what_is_below_them() -> None:
    rep = board_loading(LOADS, {}, {}, load_factors=FACTORS)
    b = {x.tag: x for x in rep.boards}
    assert [(x.tag, x.depth, x.supplied_from) for x in rep.boards] == [
        ("MSB", 0, "Primary Supply"), ("TX-1", 1, "MSB"), ("MCC-1", 2, "TX-1"), ("MCC-2", 2, "TX-1")]
    p1, p2, f1 = 75, 40 * 0.7457, math.sqrt(3) * 415 * 20 / 1000 * 0.85  # connected kW
    # MCC-1: two motors; the load with no rating is left out, the deleted one is not there at all
    assert (b["MCC-1"].loads, b["MCC-1"].left_out) == (2, 1)
    assert b["MCC-1"].connected_kw == pytest.approx(p1 + p2, abs=0.01) and b["MCC-1"].max_kw == pytest.approx((p1 + p2) * 0.75, abs=0.01)
    assert b["MCC-1"].max_kva == pytest.approx((p1 + p2) * 0.75 / 0.85, abs=0.01)
    amps = (p1 + p2) * 0.75 / 0.85 * 1000 / (math.sqrt(3) * 415)
    assert b["MCC-1"].max_amps == pytest.approx(amps, abs=0.05)
    # rated in Amps: loaded in amps
    assert (b["MCC-1"].rating, b["MCC-1"].rating_unit) == (400, "Amps")
    assert b["MCC-1"].loading_pct == pytest.approx(amps / 400 * 100, abs=0.1) and b["MCC-1"].spare == pytest.approx(400 - amps, abs=0.1)
    # MCC-2: no rating of its own, so no loading; its totals still count upstream
    assert b["MCC-2"].loading_pct is None and b["MCC-2"].problem.startswith("No rating") and b["MCC-2"].left_out == 1
    # the transformer carries both MCCs, in kVA; the main switchboard carries those and its own heater
    tx_kva = (p1 + p2 + f1) * 0.75 / 0.85
    assert b["TX-1"].loads == 3 and b["TX-1"].max_kva == pytest.approx(tx_kva, abs=0.02)
    assert (b["TX-1"].rating_unit, b["TX-1"].loading_pct) == ("kVA", pytest.approx(tx_kva / 1000 * 100, abs=0.1))
    assert b["TX-1"].over is False and b["TX-1"].spare == pytest.approx(1000 - tx_kva, abs=0.02)
    assert b["MSB"].loads == 4 and b["MSB"].connected_kw == pytest.approx(p1 + p2 + f1 + 9, abs=0.02)
    assert sorted((x.tag, x.reason, x.supplied_from) for x in rep.left_out) == [
        ("N-1", "No rating", "MCC-1"), ("U-1", "Its units (MW) are not kW, HP, Amps or kVA", "MCC-2")]


def test_the_warning_level_a_loads_own_factor_and_its_motor() -> None:
    assert board_loading(LOADS, {}, {}, load_factors=FACTORS, warn_at=10).boards[1].over is True
    loads = [_load("MCC", 100, is_panel=True, supplied_from="primary"),
             _load("P-1", 75, "MCC", lf_nameplate=1.0, lf_max_demand=0.5)]
    (mcc,) = board_loading(loads, {}, {}, load_factors=FACTORS).boards
    assert mcc.max_kw == 37.5 and mcc.avg_kw == 75  # its own factors, the list's for the rest
    assert (mcc.rating_unit, mcc.loading_pct, mcc.spare) == ("kW", 37.5, 62.5)
    loads[1].values["poles"] = 4
    with_motor = board_loading(loads, {}, {}, motors=default_motors(), load_factors=FACTORS).boards[0]
    pf = next(m for m in default_motors() if m.kw == 75 and m.poles == 4 and m.design == "Standard").pf100
    assert with_motor.max_kva == pytest.approx(37.5 / pf, abs=0.01)


def test_a_loop_in_the_supply_does_not_hang() -> None:
    loads = [_load("A", 100, "B", is_panel=True), _load("B", 100, "A", is_panel=True), _load("P-1", 10, "A")]
    rep = board_loading(loads, {}, {}, load_factors=FACTORS)
    assert sorted(x.tag for x in rep.boards) == ["A", "B"]
    assert {x.tag: x.loads for x in rep.boards} == {"A": 1, "B": 1}
