# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Nexans Olex product codes for the cable types, from the Nexans Olex Handbook 2017 product pages.

Only a code printed once for a cable (copper, unarmoured, non-flexible; V-90 PVC or X-90 XLPE
insulation; core count; conductor size) is used. A size with more than one printed code (for
example the circular and flat V-90 ranges, or two constructions of one size) has no code here and
is left blank until a choice is made: see AMBIGUOUS.

Keys are (insulation, cores, conductor size mm² as text). Each value: (product code, page).
Product codes are read from the page layout and cross-checked for the cores and size on each row.
"""

from __future__ import annotations

#: Each (insulation, cores, size) with exactly one printed product code.
CODES: dict[tuple[str, str, str], tuple[str, int]] = {
    ("V90", "2C", "1.0"): ("CACP02AA002", 12),
    ("V90", "2C", "1.5"): ("CACP05AA002", 12),
    ("V90", "2C", "2.5"): ("CACP07AA002", 12),
    ("V90", "2C", "4"): ("CACP09AA002", 12),
    ("V90", "2C", "6"): ("CACP11AA002", 12),
    ("V90", "2C", "10"): ("CACP13AA002", 12),
    ("V90", "2C", "16"): ("CACP15AA002", 12),
    ("V90", "2C+E", "1.0"): ("CNCP02AA002", 13),
    ("V90", "2C+E", "50"): ("DNHC19AA002", 14),
    ("V90", "3C", "1.5"): ("EACP05AA003", 12),
    ("V90", "3C", "2.5"): ("EACP07AA003", 12),
    ("V90", "3C", "4.0"): ("EACP09AA003", 12),
    ("V90", "3C+E", "10"): ("FNHP13AA003", 14),
    ("V90", "3C+E", "16"): ("FNHP15AA003", 14),
    ("V90", "3C+E", "35"): ("FNHC18AA003", 14),
    ("V90", "3C+E", "70"): ("FNHC20AA003", 14),
    ("V90", "3C+E", "150"): ("FNHP24AA003", 14),
    ("V90", "3C+E", "185"): ("FNHP25AA003", 14),
    ("V90", "3C+E", "240"): ("FNHP26AA003", 14),
    ("V90", "3C+E", "300"): ("FNHP27AA003", 14),
    ("V90", "4C+E", "10"): ("HNHP13AA004", 15),
    ("V90", "4C+E", "16"): ("HNHP15AA004", 15),
    ("V90", "4C+E", "25"): ("HNHC17AA004", 15),
    ("V90", "4C+E", "35"): ("HNHC18AA004", 15),
    ("V90", "4C+E", "50"): ("HNHC19AA004", 15),
    ("V90", "4C+E", "95"): ("HNHC22AA004", 15),
    ("V90", "4C+E", "120"): ("HNHP23AA004", 15),
    ("V90", "4C+E", "150"): ("HNHP24AA004", 15),
    ("V90", "4C+E", "185"): ("HNHP25AA004", 15),
    ("V90", "4C+E", "240"): ("HNHP26AA004", 15),
    ("V90", "4C+E", "300"): ("HNHP27AA004", 15),
    ("X90", "1C", "16"): ("BDBP15AA001", 10),
    ("X90", "1C", "25"): ("BDBC17AA001", 10),
    ("X90", "1C", "35"): ("BDBC18AA001", 10),
    ("X90", "1C", "50"): ("BDBC19AA001", 10),
    ("X90", "1C", "70"): ("BDBC20AA001", 10),
    ("X90", "1C", "95"): ("BDBC22AA001", 10),
    ("X90", "1C", "120"): ("BDBP23AA001", 10),
    ("X90", "1C", "150"): ("BDBP24AA001", 10),
    ("X90", "1C", "185"): ("BDBP25AA001", 10),
    ("X90", "1C", "240"): ("BDBP26AA001", 10),
    ("X90", "1C", "300"): ("BDBP27AA001", 10),
    ("X90", "1C", "400"): ("BDBP28AA001", 10),
    ("X90", "1C", "500"): ("BDBP30AA001", 10),
    ("X90", "1C", "630"): ("BDBP32AA001", 10),
    ("X90", "2C+E", "1.5"): ("DNMP05AA002", 18),
    ("X90", "2C+E", "2.5"): ("DNMP07AA002", 18),
    ("X90", "2C+E", "4"): ("DNMP09AA002", 18),
    ("X90", "2C+E", "6"): ("DNMP11AA002", 18),
    ("X90", "2C+E", "10"): ("DNMP13AA002", 18),
    ("X90", "2C+E", "70"): ("DTHC20AA002", 16),
    ("X90", "2C+E", "95"): ("DTHC22AA002", 16),
    ("X90", "2C+E", "120"): ("DTHP23AA002", 16),
    ("X90", "3C+E", "1.5"): ("FNMP05AA003", 18),
    ("X90", "3C+E", "2.5"): ("FNMP07AA003", 18),
    ("X90", "3C+E", "4"): ("FNMP09AA003", 18),
    ("X90", "3C+E", "6"): ("FNMP11AA003", 18),
    ("X90", "3C+E", "10"): ("FNMP13AA003", 18),
    ("X90", "3C+E", "25"): ("FTHC17AA003", 16),
    ("X90", "3C+E", "35"): ("FTHC18AA003", 16),
    ("X90", "3C+E", "50"): ("FTHC19AA003", 16),
    ("X90", "3C+E", "70"): ("FTHC20AA003", 16),
    ("X90", "3C+E", "95"): ("FTHC22AA003", 16),
    ("X90", "3C+E", "120"): ("FTHP23AA003", 16),
    ("X90", "4C+E", "1.5"): ("HNMP05AA004", 19),
    ("X90", "4C+E", "2.5"): ("HNMP07AA004", 19),
    ("X90", "4C+E", "4"): ("HNMP09AA004", 19),
    ("X90", "4C+E", "6"): ("HNMP11AA004", 19),
    ("X90", "4C+E", "50"): ("HTHC19AA004", 17),
    ("X90", "4C+E", "95"): ("HTHC22AA004", 17),
    ("X90", "4C+E", "150"): ("HTHP24AA004", 17),
    ("X90", "4C+E", "185"): ("HTHP25AA004", 17),
}

#: Each (insulation, cores, size) with more than one printed code: the codes, for a choice to be made.
AMBIGUOUS: dict[tuple[str, str, str], tuple[str, ...]] = {
    ("V90", "2C+E", "1.5"): ("CNCP05AA002", "CNHP05AA002", "DNHP05AA002"),
    ("V90", "2C+E", "2.5"): ("CNCP07AA002", "CNHP07AA002", "DNHP07AA002"),
    ("V90", "2C+E", "4"): ("CNCP09AA002", "CNHP09AA002", "DNHP09AA002"),
    ("V90", "2C+E", "6"): ("CNCP11AA002", "CNHP11AA002", "DNHP11AA002"),
    ("V90", "2C+E", "10"): ("CNCP13AA002", "DNHP13AA002"),
    ("V90", "2C+E", "16"): ("CNCP15AA002", "DNHP15AA002"),
    ("V90", "3C+E", "1.5"): ("ENCP05AA003", "ENHP05AA003", "FNHP05AA003"),
    ("V90", "3C+E", "2.5"): ("ENCP07AA003", "ENHP07AA003", "FNHP07AA003"),
    ("V90", "3C+E", "4"): ("ENHP09AA003", "FNHP09AA003"),
    ("V90", "3C+E", "6"): ("ENHP11AA003", "FNHP11AA003"),
    ("V90", "4C+E", "1.5"): ("GNHP05AA004", "HNHP05AA004"),
    ("V90", "4C+E", "2.5"): ("GNHP07AA004", "HNHP07AA004"),
    ("V90", "4C+E", "4"): ("GNHP09AA004", "HNHP09AA004"),
    ("V90", "4C+E", "6"): ("GNHP11AA004", "HNHP11AA004"),
    ("X90", "2C+E", "16"): ("DTHP15AA002", "DNMP15AA002"),
    ("X90", "2C+E", "25"): ("DTHC17AA002", "DNMC17AA002"),
    ("X90", "2C+E", "35"): ("DTHC18AA002", "DNMC18AA002"),
    ("X90", "2C+E", "50"): ("DTHC19AA002", "DNMC19AA002"),
    ("X90", "3C+E", "16"): ("FTHP15AA003", "FNMP15AA003"),
    ("X90", "3C+E", "150"): ("FTHP24AA003", "FNMP24AA003"),
    ("X90", "3C+E", "185"): ("FTHP25AA003", "FNMP25AA003"),
    ("X90", "3C+E", "240"): ("FTHP26AA003", "FNMP26AA003"),
    ("X90", "3C+E", "300"): ("FTHP27AA003", "FNMP27AA003"),
    ("X90", "4C+E", "10"): ("HTHP13AA004", "HNMP13AA004"),
    ("X90", "4C+E", "16"): ("HTHP15AA004", "HNMP15AA004"),
    ("X90", "4C+E", "25"): ("HTHC17AA004", "HNMC17AA004"),
    ("X90", "4C+E", "35"): ("HTHC18AA004", "HNMC18AA004"),
    ("X90", "4C+E", "70"): ("HTHC20AA004", "HNMC20AA004"),
    ("X90", "4C+E", "120"): ("HTHP23AA004", "HNMP23AA004"),
    ("X90", "4C+E", "240"): ("HTHP26AA004", "HNMP26AA004"),
    ("X90", "4C+E", "300"): ("HTHP27AA004", "HNMP27AA004"),
}


def product_code(insulation: str, cores: str, size: str) -> str:
    """The one printed product code for this cable, or "" (none printed, or more than one).
    `insulation` is the handbook's name: "V90" (V-90 PVC) or "X90" (X-90 XLPE)."""
    return CODES.get((insulation, cores, size), ("", 0))[0]


__all__ = ["AMBIGUOUS", "CODES", "product_code"]
