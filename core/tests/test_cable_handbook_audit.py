# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Audit of the cable data against the Nexans Olex Handbook 2017.

core/tests/data/nexans_handbook_rows.json holds the handbook's own text: each product's line
(its columns, in reading order, up to its product code) and each rating page's words. Every
stored size, core count, overall diameter and current rating is checked against it here, by
rules written separately from the ones that produced the data (scripts/nexans_handbook_extract.py).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from workbench_core.keylists.cable_ampacity import TABLES
from workbench_core.keylists.cable_dimensions import DIMENSIONS
from workbench_core.keylists.cable_handbook import RECORDS
from workbench_core.keylists.cable_mass import MASS
from workbench_core.keylists.cable_types import HANDBOOK, default_cable_types

ROWS = json.loads((Path(__file__).parent / "data" / "nexans_handbook_rows.json").read_text(encoding="utf-8"))
RECORD = {r[0]: r for r in RECORDS}
NUMBER = re.compile(r"^\d+(\.\d+)?$")


def _numbers(line: str) -> list[float]:
    return [float(t) for t in line.split() if NUMBER.match(t)]


def test_every_printed_product_is_stored_once() -> None:
    printed = [code for _, code, _ in ROWS["products"]]
    assert len(printed) == len(set(printed)) == 470
    assert set(printed) == set(RECORD) == set(DIMENSIONS)
    stored = [c.product_code for c in default_cable_types() if c.product_code]
    assert sorted(stored) == sorted(printed)  # each on exactly one cable type


def test_each_products_size_and_overall_diameter_are_on_its_line() -> None:
    for page, code, line in ROWS["products"]:
        size, od, minor = float(RECORD[code][5]), DIMENSIONS[code][0], DIMENSIONS[code][1]
        numbers = _numbers(line)
        if page not in (22, 23):  # control cables: the size is the heading above the rows, not on the line
            assert size in numbers[:2], (page, code, line)
        assert od in numbers, (page, code, line)
        # the overall diameter is the column before the mass (and before what a page prints after the mass)
        after = {34: 3, 36: 3, 39: 2}.get(page, 1) + (1 if minor is not None else 0)
        assert numbers[-1 - after] == od, (page, code, line)
        if minor is not None:
            assert page in (12, 13) and numbers[-2] == minor and " X " in line.upper(), (page, code, line)  # width X height


def test_each_products_mass_is_the_column_after_its_overall_diameter() -> None:
    """The pages print the approximate mass in kg/100 m; it is stored in kg/m."""
    import math

    assert set(MASS) == set(DIMENSIONS)
    for page, code, line in ROWS["products"]:
        numbers = _numbers(line)
        od, minor = DIMENSIONS[code][0], DIMENSIONS[code][1]
        at = len(numbers) - {34: 3, 36: 3, 39: 2}.get(page, 1)
        assert MASS[code] == round(numbers[at] / 100, 4), (page, code, line)
        assert numbers[at - 1] == (minor if minor is not None else od), (page, code, line)
        # a cable weighs between a third of and twelve times what water of its size would (copper is 8.9)
        area_m2 = math.pi * (od / 2000) ** 2 if minor is None else (od / 1000) * (minor / 1000)
        assert 300 < MASS[code] / area_m2 < 12000, (page, code, line)
    assert MASS["BAAP32AA001"] == 6.13  # 630 mm² single core: 5.6 kg/m of copper and its insulation
    by_code = {c.product_code: c for c in default_cable_types() if c.product_code}
    assert all(by_code[code].mass_kg_per_m == mass for code, mass in MASS.items())


def test_core_counts_follow_the_rows_and_headings() -> None:
    # control cables and the ceramifiable multicores print the cores at the start of each line
    for page, code, line in ROWS["products"]:
        first = line.split()[0]
        if page in (22, 23):
            assert RECORD[code][4] == first.replace("+E", "C+E"), (code, line)
            assert RECORD[code][5] in ("1.5", "2.5")
        if page == 37:
            assert RECORD[code][4] == (first.replace("+E", "C+E") if "+E" in first else f"{first}C"), (code, line)
    by_page = {}
    for r in RECORDS:
        by_page.setdefault(r[9], set()).add(r[4])
    assert by_page[38] == by_page[39] == {"3C+3E"} and by_page[10] == by_page[30] == {"1C"}
    assert by_page[22] >= {"5C+E", "20C+E", "50C+E"} and by_page[28] == {"1C", "2C+E"}


def test_families_are_the_pages_own() -> None:
    family = lambda code: (RECORD[code][1], RECORD[code][2], RECORD[code][3], RECORD[code][7])  # noqa: E731
    assert family("DNMP05AA002") == ("V-90 PVC SWA circular", "PVC", "0.6/1kV", True)  # page 18, not XLPE unarmoured
    assert family("DTMP15AA002") == ("X-90 XLPE/PVC SWA multicore", "XLPE", "0.6/1kV", True)
    assert RECORD["CNHP05AA002"][3] == "450/750V" and RECORD["DNHP05AA002"][3] == "0.6/1kV"  # page 14: by range
    assert RECORD["GNHP05AA004"][3] == "450/750V" and RECORD["HNHP05AA004"][3] == "0.6/1kV"
    assert "non-flexible conductor" in RECORD["PDGP07AA002"][1]  # printed with an asterisk


def test_bending_radii_follow_the_handbooks_table() -> None:
    def radii(code: str):
        return DIMENSIONS[code][2], DIMENSIONS[code][3]
    assert radii("BAAP01AA001") == (9.6, 14.4)  # 2.4 mm: 4 and 6 times
    assert radii("BDBP28AA001") == (199.8, 299.7)  # 33.3 mm, over 25 mm: 6 and 9 times
    assert radii("DNMP05AA002") == (169.2, 253.8)  # SWA, 14.1 mm: 12 and 18 times
    assert radii("FTDP07AA003") == (175.2, 262.8)  # copper tape screened: 12 and 18 times
    assert radii("BDSX01AA001") == (34.0, None) and radii("EAHR02AA003")[1] is None  # flexible: 4 times, installed
    assert radii("PFLX01AA001") == (None, 40.0) and radii("FTDR04AA003") == (162.0, None)  # as printed (pages 34, 39)
    # page 39's printed installed radius is 12 times the diameter, the rule used for page 38
    for page, code, line in ROWS["products"]:
        if page == 39:
            assert abs(DIMENSIONS[code][2] - 12 * DIMENSIONS[code][0]) <= 5, code
    # nothing where the handbook gives nothing: flat cables, aluminium, Envirolex and Alsecure multicores
    for code in ("CACP02AA002", "BDBA17AA001", "XDAB17AA002", "XDDS25AA004", "BZHX01AA001", "PEKP07AA002"):
        assert radii(code) == (None, None) and DIMENSIONS[code][4], code


def test_every_current_rating_is_on_its_page_in_reading_order() -> None:
    checked = 0
    for key, table in TABLES.items():
        words = ROWS["ratings"][str(table["page"])]
        methods = list(table["amps"])
        for size in table["amps"]["unenclosed_space"]:
            want = [str(table["amps"][m][size]) for m in methods if size in table["amps"][m]]
            # after the size: the copper figures, alone or each followed by its aluminium figure
            found = any(w == size and (words[i + 1:i + 1 + len(want)] == want or words[i + 1:i + 1 + 2 * len(want):2] == want)
                        for i, w in enumerate(words))
            assert found, (key, size, want)
            checked += 1
    assert checked == 196 and len(TABLES) == 10


def test_default_types_use_the_table_for_their_circuit() -> None:
    cables = {c.code: c for c in default_cable_types() if c.application != HANDBOOK}
    one = cables["AC_415V - Power - 1C - 16"]  # three single cores, three phase: page 74, not the two-cable table
    assert one.ampacity["unenclosed_space"] == 108 and "page 74" in one.ampacity_source
    assert cables["AC_240V - Power - 2C+E - 25"].ampacity["unenclosed_space"] == 140  # two core, single phase: page 69
    assert cables["AC_415V - Power - 3C+E - 25"].ampacity["unenclosed_space"] == 119  # 3 and 4 core, three phase: page 80
    assert not any("40 °C" in c.ampacity_source for c in cables.values())  # the handbook states no ambient for these tables
