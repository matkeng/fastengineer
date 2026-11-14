# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Overall diameter and bending radii of the handbook's products (keylists.cable_dimensions)."""

from __future__ import annotations

import pytest

from workbench_core.keylists.cable_dimensions import DIMENSIONS
from workbench_core.keylists.cable_types import default_cable_types


def _by_code(code: str):
    return next(c for c in default_cable_types() if c.product_code == code)


def test_every_handbook_product_has_its_overall_diameter() -> None:
    cables = [c for c in default_cable_types() if c.product_code]
    assert len(cables) == 469 and all(c.overall_diameter_mm for c in cables)


def test_a_small_pvc_cable_is_4_and_6_times_its_diameter() -> None:
    c = _by_code("BAAP01AA001")  # 0.5 mm² single core V-90 PVC, page 8: overall diameter 2.4 mm
    assert (c.overall_diameter_mm, c.bend_installed_mm, c.bend_pulling_mm) == (2.4, 9.6, 14.4)
    assert "up to 25 mm" in c.bend_basis


def test_a_large_pvc_or_xlpe_cable_is_6_and_9_times_its_diameter() -> None:
    c = _by_code("BDBP28AA001")  # 400 mm² single core XLPE/PVC, page 10: overall diameter 33.3 mm
    assert c.overall_diameter_mm == 33.3
    assert c.bend_installed_mm == pytest.approx(199.8) and c.bend_pulling_mm == pytest.approx(299.7)
    assert "over 25 mm" in c.bend_basis


def test_armoured_and_aluminium_cables_use_their_own_rules() -> None:
    swa = _by_code("BFCP05AA006")  # PVC SWA control, page 23: overall diameter 18.0 mm, multicore SWA
    assert (swa.bend_installed_mm, swa.bend_pulling_mm) == (216.0, 324.0)
    alu = _by_code("XDDS25AA004")  # 185 mm² aluminium URD, page 24: overall diameter 43.6 mm
    assert (alu.bend_installed_mm, alu.bend_pulling_mm) == (348.8, 523.2)
    assert "aluminium" in alu.bend_basis and alu.description.startswith("X-90 XLPE URD power, aluminium")


def test_radii_printed_on_the_page_are_copied_exactly() -> None:
    c = _by_code("PFLX01AA001")  # Alsecure Plus mica tape, page 34: minimum bending radius during installation 40 mm
    assert c.bend_pulling_mm == 40.0 and c.bend_installed_mm is None and c.overall_diameter_mm == 8.9
    assert "printed" in c.bend_basis


def test_families_without_a_handbook_rule_stay_blank() -> None:
    for code in ("BDSX01AA001", "BZHX01AA001", "PTHR04AA002", "FTDP07AA003", "EAHR02AA003"):  # flexible, Envirolex, VSD, cords
        c = _by_code(code)
        assert c.overall_diameter_mm is not None and c.bend_installed_mm is None and c.bend_pulling_mm is None, code
    assert len(DIMENSIONS) == 469 and sum(1 for v in DIMENSIONS.values() if v[1] is not None) == 271
