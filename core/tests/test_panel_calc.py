# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
import pytest

from workbench_core.keylists.panel_calc import default_pole_watts, panel_totals


def test_three_phase_totals() -> None:
    t = panel_totals([("R", 6000), ("W", 4000), ("B", 1500), ("B", 500)], three_phase=True, voltage=240, power_factor=0.85,
                     isolator_rating=250)
    assert t.phases == ["R", "W", "B"] and t.phase_w == [6000, 4000, 2000]
    assert t.phase_kva == pytest.approx([7.059, 4.706, 2.353], abs=0.001)
    assert t.phase_amps == pytest.approx([29.41, 19.61, 9.80], abs=0.01)
    assert t.max_amps == pytest.approx(29.41, abs=0.01) and t.total_kw == 12
    assert t.remaining_amps == pytest.approx(220.59, abs=0.01) and t.remaining_pct == pytest.approx(88.24, abs=0.01)
    assert t.max_kva == 180


def test_single_phase_totals() -> None:
    t = panel_totals([("", 2400), ("R", 2400)], three_phase=False, voltage=240, power_factor=1, isolator_rating=63)
    assert (t.phases, t.phase_w, t.phase_amps) == ([""], [4800], [20])
    assert (t.max_amps, t.total_kw, t.remaining_amps, t.max_kva) == (20, 4.8, 43, 15.12)


def test_nothing_to_divide_by() -> None:
    t = panel_totals([("R", 1000)], three_phase=True, voltage=0, power_factor=0, isolator_rating=0)
    assert (t.max_amps, t.phase_kva, t.remaining_pct, t.max_kva, t.total_kw) == (0, [0, 0, 0], None, 0, 1)


def test_default_watts() -> None:
    assert default_pole_watts(15, "kW", 3, 240, 0.85) == 5000
    assert default_pole_watts(2.4, "kW", 1, 240, 0.85) == 2400
    assert default_pole_watts(10, "Amps", 3, 240, 0.85) == pytest.approx(2040)
    assert default_pole_watts(None, "kW", 1, 240, 0.85) is None
