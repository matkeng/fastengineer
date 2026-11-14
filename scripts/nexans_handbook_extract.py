# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Read the product pages of the Nexans Olex Handbook 2017 and write the cable data modules.

    python scripts/nexans_handbook_extract.py "Handbook 2017 Online.pdf"

Needs `pdftotext` (poppler). Each product is one line of the page's text in reading order:
its columns, then its product code. PAGES says, for each page, what the family is and which
column is which. Writes:
    core/src/workbench_core/keylists/cable_handbook.py     every product
    core/src/workbench_core/keylists/cable_dimensions.py   overall diameter and bending radii
    core/src/workbench_core/keylists/cable_products.py     the codes of the default cable types
    core/tests/data/nexans_handbook_rows.json              the lines read and the rating pages' text, for the audit test
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEYLISTS = ROOT / "core" / "src" / "workbench_core" / "keylists"
CODE = re.compile(r"\b([A-Z]{4}\d{2,3}[A-Z]{2}\d{3})(\*?)")
NUMBER = re.compile(r"^\d+(\.\d+)?$")
CORES_HEADING = re.compile(r"^(\d)C(\+E)?$")
SIZE_HEADING = re.compile(r"^(\d+(\.\d+)?)mm2 \(")
BEND_PAGE = 94  # "Cable minimum installed bending radii", GENERAL DATA

# page: (family, insulation, voltage, armoured, flexible, cores when the page has no core heading)
PAGES: dict[int, tuple[str, str, str, bool, bool, str]] = {
    8: ("V-90 PVC single core copper", "PVC", "0.6/1kV", False, False, "1C"),
    9: ("V-90 PVC SDI single core copper", "PVC", "450/750V", False, False, "1C"),
    10: ("X-90 XLPE/PVC single core copper", "XLPE", "0.6/1kV", False, False, "1C"),
    11: ("X-90 XLPE/PVC single core aluminium", "XLPE", "0.6/1kV", False, False, "1C"),
    12: ("V-90 PVC flat", "PVC", "450/750V", False, False, ""),
    13: ("V-90 PVC flat with earth", "PVC", "450/750V", False, False, ""),
    14: ("V-90 PVC circular", "PVC", "", False, False, ""),
    15: ("V-90 PVC circular", "PVC", "", False, False, ""),
    16: ("X-90 XLPE/PVC multicore", "XLPE", "0.6/1kV", False, False, ""),
    17: ("X-90 XLPE/PVC multicore", "XLPE", "0.6/1kV", False, False, ""),
    18: ("V-90 PVC SWA circular", "PVC", "0.6/1kV", True, False, ""),
    19: ("V-90 PVC SWA circular", "PVC", "0.6/1kV", True, False, ""),
    20: ("X-90 XLPE/PVC SWA multicore", "XLPE", "0.6/1kV", True, False, ""),
    21: ("X-90 XLPE/PVC SWA multicore", "XLPE", "0.6/1kV", True, False, ""),
    22: ("V-90 PVC control", "PVC", "0.6/1kV", False, False, ""),
    23: ("V-90 PVC SWA control", "PVC", "0.6/1kV", True, False, ""),
    24: ("X-90 XLPE URD power", "XLPE", "0.6/1kV", False, False, "4C"),
    25: ("X-90 XLPE aerial bundled aluminium", "XLPE", "0.6/1kV", False, False, ""),
    28: ("Versolex X-90 TPE-90 flexible", "XLPE", "0.6/1kV", False, True, "1C"),
    29: ("Versolex X-90 TPE-90 flexible", "XLPE", "0.6/1kV", False, True, ""),
    30: ("Envirolex 110 °C single core", "X-HF-110", "0.6/1kV", False, True, "1C"),
    31: ("Envirolex 110 °C multicore", "X-HF-110", "0.6/1kV", False, True, ""),
    34: ("Alsecure Plus mica tape single core", "X-HF-110", "0.6/1kV", False, True, "1C"),
    35: ("Alsecure Plus mica tape multicore", "X-HF-110", "0.6/1kV", False, True, ""),
    36: ("Alsecure Premium ceramifiable single core", "HFI-90-TP", "0.6/1kV", False, True, "1C"),
    37: ("Alsecure Premium ceramifiable multicore", "HFI-90-TP", "0.6/1kV", False, False, ""),
    38: ("Varolex VSD/EMC copper tape screened", "XLPE", "0.6/1kV", False, False, "3C+3E"),
    39: ("Varolex VSD flexible copper tape screened", "XLPE", "0.6/1kV", False, True, "3C+3E"),
    40: ("Powerlex V-90 PVC OD flexible cord", "PVC", "250/440V", False, True, ""),
    41: ("Powerlex V-90 PVC HD flexible cord", "PVC", "0.6/1kV", False, True, ""),
}
#: Pages 14 and 15: the voltage grade goes with the product range (the code's first four letters).
VOLTAGE_BY_RANGE = {"CNHP": "450/750V", "ENHP": "450/750V", "GNHP": "450/750V",
                    "DNHP": "0.6/1kV", "FNHP": "0.6/1kV", "HNHP": "0.6/1kV"}
ALUMINIUM_PAGES = (11, 25)
ALUMINIUM_RANGES_P24 = ("XDD",)  # page 24: the rows under "LV Distribution – Aluminium"


def page_lines(pdf: str, page: int) -> list[str]:
    out = subprocess.run(["pdftotext", "-raw", "-f", str(page), "-l", str(page), pdf, "-"], capture_output=True, text=True, check=True)
    return [line.strip() for line in out.stdout.splitlines()]


def read_products(pdf: str) -> tuple[list[dict], list[list]]:
    products, lines_read = [], []
    for page, (family, insulation, voltage, armoured, flexible, default_cores) in PAGES.items():
        cores, heading_size = default_cores, ""
        for line in page_lines(pdf, page):
            if CORES_HEADING.match(line):
                cores = line
                continue
            if SIZE_HEADING.match(line):
                heading_size = SIZE_HEADING.match(line).group(1)
                continue
            if line.startswith("Single Core") and page in (8, 41):
                if page == 8:
                    family = "V-90 PVC single core copper earth conductor"
                cores = "1C"
                continue
            m = CODE.search(line)
            if not m:
                continue
            tokens = line[:m.start()].replace(" X ", " ").split()
            numbers = [float(t) for t in tokens if NUMBER.match(t)]
            construction = next((t for t in tokens if t in ("Solid", "Stranded", "Compacted")), "")
            row_cores, size = cores, tokens[0]
            if page in (22, 23):  # "20+E 21.5 61": the cores lead the row; the size is the heading above
                row_cores, size = tokens[0].replace("+E", "C+E"), heading_size
            elif page == 37:  # "2 2.5 ..." (no earth) or "2+E 2.5 ..."
                row_cores, size = (tokens[0].replace("+E", "C+E") if "+E" in tokens[0] else tokens[0] + "C"), tokens[1]
            size = f"{float(size):g}"
            minor = bend_printed = None
            if page in (12, 13):  # flat: width X height, mass
                od, minor = numbers[-3], numbers[-2]
            elif page in (34, 36):  # ..., overall, mass, bending radius during install, pulling tension
                od, bend_printed = numbers[-4], numbers[-2]
            elif page == 39:  # ..., overall, mass, bend radius installed
                od, bend_printed = numbers[-3], numbers[-1]
            else:  # ..., overall, mass
                od = numbers[-2]
            code = m.group(1)
            aluminium = page in ALUMINIUM_PAGES or (page == 24 and code.startswith(ALUMINIUM_RANGES_P24))
            fam = family
            if page == 24:
                fam += ", aluminium" if aluminium else ", copper"
            products.append({
                "code": code, "page": page, "family": fam, "insulation": insulation,
                "voltage": VOLTAGE_BY_RANGE.get(code[:4], voltage) if page in (14, 15) else voltage,
                "cores": row_cores, "size": size, "construction": construction, "armoured": armoured, "flexible": flexible,
                "aluminium": aluminium, "od": od, "minor": minor, "bend_printed": bend_printed,
                "note": "non-flexible conductor" if m.group(2) else ""})
            lines_read.append([page, code, line[:m.start()].strip()])
    return products, lines_read


def bending(p: dict) -> tuple[float | None, float | None, str]:
    """(installed, pulling, basis): the handbook's page 94 rule for the product, or what its page prints."""
    od, page = p["od"], p["page"]
    rule = f"page {BEND_PAGE}"
    if page in (34, 36):
        return None, p["bend_printed"], f"printed on page {page}: minimum bending radius during installation"
    if page == 39:
        return p["bend_printed"], None, f"printed on page {page}: minimum bend radius (installed)"
    if p["minor"] is not None:
        return None, None, "flat cable (width × height): the handbook's rule is on an overall diameter"
    if p["aluminium"]:
        return None, None, f"{rule} has a rule for solid aluminium conductors only; not applied to this cable"
    if p["armoured"]:
        return round(12 * od, 1), round(18 * od, 1), f"{rule}: multicore SWA or metal tape: 12 and 18 times the overall diameter"
    if page == 38:
        return round(12 * od, 1), round(18 * od, 1), (f"{rule}: multicore SWA or metal tape (copper tape screened): 12 and 18 "
                                                       "times the overall diameter")
    if page in (28, 29):
        return round(4 * od, 1), None, f"{rule}: flexible cables (incl. Versolex): 4 times the overall diameter, installed"
    if page in (40, 41):
        return round(4 * od, 1), None, f"{rule}: flexible cords: 4 times the overall diameter, installed"
    if p["flexible"] or page == 37:
        return None, None, f"{rule} has no rule for this cable's materials"  # Envirolex, Alsecure
    small = od <= 25
    a, b = (4, 6) if small else (6, 9)
    return round(a * od, 1), round(b * od, 1), (f"{rule}: PVC or XLPE single and multicore, overall diameter "
                                                 f"{'to and including' if small else 'over'} 25 mm: {a} and {b} times the overall diameter")


HEADER = "# SPDX-License-Identifier: AGPL-3.0-only\n# Copyright (C) 2026 Matthew Kelly\n"
GENERATED = "Written by scripts/nexans_handbook_extract.py from the handbook's pages: change the script, not this file."


def write_modules(products: list[dict], lines_read: list[list], ratings: dict[str, list[str]]) -> None:
    out = [HEADER + f'''"""Every product on the product pages (8 to 41) of the Nexans Olex Handbook 2017.

{GENERATED}
"""

from __future__ import annotations

#: (product code, family, insulation, voltage, cores, size mm², construction, armoured, flexible, page)
RECORDS: tuple[tuple[str, str, str, str, str, str, str, bool, bool, int], ...] = (''']
    for p in products:
        fam = p["family"] + (f" ({p['note']})" if p["note"] else "")
        out.append("    (" + ", ".join(json.dumps(p[k], ensure_ascii=False) for k in ("code",)) + f", {json.dumps(fam, ensure_ascii=False)}, "
                   + ", ".join(json.dumps(p[k]) for k in ("insulation", "voltage", "cores", "size", "construction"))
                   + f", {p['armoured']}, {p['flexible']}, {p['page']}),")
    out.append(')\n\n\n__all__ = ["RECORDS"]\n')
    (KEYLISTS / "cable_handbook.py").write_text("\n".join(out), encoding="utf-8")

    out = [HEADER + f'''"""Overall diameter and bending radii of the Nexans Olex Handbook 2017 products.

- overall: the "overall diameter" printed on the product page (a flat cable: its width, with its
  height as `minor`; an aerial bundled cable: the diameter over the laid-up cores).
- installed: the minimum installed bending radius; pulling: the minimum bending radius during
  installation. From the handbook's "Cable minimum installed bending radii" (page {BEND_PAGE}) as a
  factor times the overall diameter, or as printed on the product page. None where the handbook
  gives no figure; `basis` says which rule was used, or why there is none.

{GENERATED}
"""

from __future__ import annotations

#: product code -> (overall mm, minor mm (flat cables), installed mm, pulling mm, basis)
DIMENSIONS: dict[str, tuple[float, float | None, float | None, float | None, str]] = {{''']
    for p in products:
        installed, pulling, basis = bending(p)
        out.append(f'    "{p["code"]}": ({p["od"]}, {p["minor"]}, {installed}, {pulling}, {json.dumps(basis, ensure_ascii=False)}),')
    out.append('}\n\n\n__all__ = ["DIMENSIONS"]\n')
    (KEYLISTS / "cable_dimensions.py").write_text("\n".join(out), encoding="utf-8")

    # the default cable types' codes: copper, unarmoured, fixed wiring, V-90 PVC or X-90 XLPE
    index: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for p in products:
        if p["page"] in (10, 12, 13, 14, 15, 16, 17):
            index[("V90" if p["insulation"] == "PVC" else "X90", p["cores"], p["size"])].append(p)
    order = lambda kv: (kv[0][0], kv[0][1], float(kv[0][2]))  # noqa: E731
    out = [HEADER + f'''"""Nexans Olex product codes for the default cable types, from the Nexans Olex Handbook 2017.

Only a code printed once for a cable (copper, unarmoured, fixed wiring; V-90 PVC or X-90 XLPE;
core count; conductor size) is used. A size with more than one printed code (the flat and circular
V-90 ranges, the 450/750 V and 0.6/1 kV ranges) has no code and is in AMBIGUOUS, for a choice.
Keys: (insulation "V90" or "X90", cores, conductor size mm² as text). Values: (product code, page).

{GENERATED}
"""

from __future__ import annotations

CODES: dict[tuple[str, str, str], tuple[str, int]] = {{''']
    for key, found in sorted(index.items(), key=order):
        if len(found) == 1:
            out.append(f'    {key!r}: ("{found[0]["code"]}", {found[0]["page"]}),'.replace("'", '"'))
    out.append("}\n\nAMBIGUOUS: dict[tuple[str, str, str], tuple[str, ...]] = {")
    for key, found in sorted(index.items(), key=order):
        if len(found) > 1:
            out.append(f'    {key!r}: ({", ".join(json.dumps(p["code"]) for p in found)}),'.replace("'", '"'))
    out.append('''}


def product_code(insulation: str, cores: str, size: str) -> str:
    """The one printed product code for this cable, or "" (none printed, or more than one).
    `insulation` is the handbook's name: "V90" (V-90 PVC) or "X90" (X-90 XLPE)."""
    return CODES.get((insulation, cores, size), ("", 0))[0]


__all__ = ["AMBIGUOUS", "CODES", "product_code"]
''')
    (KEYLISTS / "cable_products.py").write_text("\n".join(out), encoding="utf-8")

    data = ROOT / "core" / "tests" / "data"
    data.mkdir(exist_ok=True)
    (data / "nexans_handbook_rows.json").write_text(json.dumps({"products": lines_read, "ratings": ratings}, ensure_ascii=False, indent=0),
                                                    encoding="utf-8")


if __name__ == "__main__":
    found, read = read_products(sys.argv[1])
    # the rating pages (cable_ampacity.TABLES), each as its numbers and words in reading order
    rating_pages = (61, 62, 63, 64, 67, 69, 72, 74, 78, 80)
    write_modules(found, read, {str(p): " ".join(page_lines(sys.argv[1], p)).split() for p in rating_pages})
    print(f"{len(found)} products on {len(PAGES)} pages")
