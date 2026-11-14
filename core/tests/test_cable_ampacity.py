# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""The Nexans Olex handbook's current ratings (cable_ampacity) and the cable types that carry them."""

from __future__ import annotations


from workbench_core.keylists.cable_ampacity import METHODS, TABLES, ampacity
from workbench_core.keylists.cable_types import CableType, check_cable_types, default_cable_types


def test_values_checked_against_the_printed_page() -> None:
    # page 61 (1 core V-90 PVC, solid), page 62 (flexible) and page 63 (1 core XLPE): compared with the rendered page
    assert ampacity("1C-PVC", "1") == {"unenclosed_space": 16, "spaced_from_surface": 16, "touching": 13, "enclosed_conduit_in_air": 13}
    assert ampacity("1C-PVC", "25") == {"unenclosed_space": 124, "spaced_from_surface": 119, "touching": 97, "enclosed_conduit_in_air": 94}
    assert ampacity("1C-PVC", "630") == {"unenclosed_space": 1014, "spaced_from_surface": 897, "touching": 770}  # no enclosed-in-conduit figure
    assert ampacity("1C-XLPE", "16") == {"unenclosed_space": 112, "spaced_from_surface": 108, "touching": 86, "enclosed_conduit_in_air": 84}
    assert ampacity("1C-XLPE", "300")["unenclosed_space"] == 787
    assert ampacity("1C-PVC-flex", "2.5") == {"unenclosed_space": 29, "spaced_from_surface": 28, "touching": 22, "enclosed_conduit_in_air": 24}
    assert ampacity("1C-PVC-flex", "630") == {"unenclosed_space": 1036, "spaced_from_surface": 914, "touching": 785}


def test_every_table_is_copper_in_air_and_in_order() -> None:
    for key, t in TABLES.items():
        assert set(t["amps"]) <= set(METHODS), key
        for method, values in t["amps"].items():
            sizes = [float(s) for s in values]
            amps = list(values.values())
            assert amps == sorted(amps), (key, method)  # a bigger cable carries more
            assert all(s > 0 for s in sizes)


def test_the_basis_is_recorded() -> None:
    assert {t["verified"] for t in TABLES.values()} == {"image", "text"}
    assert {k for k, t in TABLES.items() if t["phase"] == "three"} == {"3C4C-PVC", "3C4C-XLPE", "3x1C-PVC", "3x1C-XLPE"}
    assert TABLES["2C-PVC"]["page"] == 67 and TABLES["3C4C-XLPE"]["page"] == 80


def _by_code(code: str) -> CableType:
    return next(c for c in default_cable_types() if c.code == code)


def test_default_cable_types_carry_the_handbook_figures() -> None:
    c = _by_code("AC_415V - Power - 3C+E - 25")  # X90 3 core + earth, 25 mm²: 3 and 4 core XLPE, page 80
    assert c.conductor_mm2 == 25 and c.ampacity["unenclosed_space"] == 119 and "page 80" in c.ampacity_source
    # single cores on AC_415V are three cables, three phase: page 74 (not the two-cable, single phase table)
    assert _by_code("AC_415V - Power - 1C - 630").ampacity["touching"] == 938
    assert ampacity("3x1C-XLPE", "16") == {"unenclosed_space": 108, "spaced_from_surface": 92, "touching": 86, "enclosed_conduit_in_air": 72}
    assert _by_code("AC_415V - Power - 3C+E - 1.5").ampacity["unenclosed_space"] == 16  # V-90 PVC, page 78
    # not in any table: earth, VSD, pilot, flexible TPE and network cables
    for code in ("AC_415V - Power VSD - 3C+3E - 25", "Earth - PVC - 1C - 25", "AC_240V - Power Flex - 2C+E - 1.5",
                 "AC_415V - Power Pilot - 3C+E+Pilot - 1.5"):
        if any(c.code == code for c in default_cable_types()):
            assert _by_code(code).ampacity == {}, code
    assert sum(1 for c in default_cable_types() if c.ampacity) == 59


def test_a_form_that_does_not_show_the_figures_does_not_lose_them() -> None:
    saved = _by_code("AC_415V - Power - 3C+E - 25").model_dump(mode="json")
    edited = dict(saved, description="edited in the form")
    for field in ("ampacity", "ampacity_source", "conductor_mm2"):
        edited.pop(field)  # a client that sends only the fields it shows
    out = check_cable_types([edited])[0]
    assert out.description == "edited in the form"
    assert out.ampacity == {} and out.conductor_mm2 is None  # the figures are only kept when sent back (the editor sends the whole row)
    kept = check_cable_types([saved])[0]
    assert kept.ampacity == _by_code("AC_415V - Power - 3C+E - 25").ampacity and kept.conductor_mm2 == 25


def test_a_bad_figure_from_the_form_is_dropped_not_stored() -> None:
    raw = {"code": "X", "ampacity": {"touching": "lots", "nonsense": 9, "spaced_from_surface": 12}, "conductor_mm2": "abc"}
    out = check_cable_types([raw])[0]
    assert out.ampacity == {"spaced_from_surface": 12.0} and out.conductor_mm2 is None


def test_product_codes_are_the_printed_ones() -> None:
    from workbench_core.keylists.cable_products import AMBIGUOUS, CODES, product_code
    from workbench_core.keylists.cable_types import HANDBOOK
    # page 16 (2C+E XLPE multicore, 70 mm²), page 14 (3C+E V-90 circular, 10 mm²), page 10 (single core XLPE)
    assert _by_code("AC_240V - Power - 2C+E - 70").product_code == "DTHC20AA002"
    assert _by_code("AC_415V - Power - 3C+E - 10").product_code == "FNHP13AA003"
    assert product_code("X90", "1C", "630") == "BDBP32AA001"
    # sizes printed more than once (flat and circular, 450/750 V and 0.6/1 kV) stay blank until chosen
    assert _by_code("AC_415V - Power - 3C+E - 1.5").product_code == ""
    assert set(AMBIGUOUS[("V90", "3C+E", "1.5")]) == {"ENCP05AA003", "ENHP05AA003", "FNHP05AA003"}
    assert not set(CODES) & set(AMBIGUOUS)
    defaults = [c for c in default_cable_types() if c.application != HANDBOOK]
    have = [c for c in defaults if c.product_code]
    assert len(have) == 44 and len({c.product_code for c in have}) == 44
    assert all(c.description in ("Cu-PVC-PVC-V90 (Power)", "Cu-XLPE-PVC-X90 (Power)") for c in have)


def test_the_load_list_chooses_from_the_defaults_only() -> None:
    from workbench_core.keylists.cable_types import HANDBOOK
    defaults = [c for c in default_cable_types() if c.application != HANDBOOK]
    assert len(defaults) == 218 and {c.insulation for c in defaults if c.insulation} == {"PVC", "XLPE"}


def test_a_typed_product_code_is_kept_as_typed() -> None:
    saved = _by_code("AC_240V - Power - 2C+E - 70").model_dump(mode="json")
    assert check_cable_types([saved])[0].product_code == "DTHC20AA002"
    assert check_cable_types([dict(saved, product_code="  dthc20aa002 ")])[0].product_code == "dthc20aa002"
