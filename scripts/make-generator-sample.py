# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Write samples/generator-sample.xlsx: a small generator workbook with invented data.

It has the structure the importer reads (tblConfig, tblRunSheet with a labels row and a tags
row, tblTemplates in contiguous blocks with concat / exists / lookup formulas and late F=
formulas, Parents, lookup sheets) so the app, the engine tests and CI can exercise the whole
flow without any project data.

    python scripts/make-generator-sample.py [output.xlsx]
"""

from __future__ import annotations

import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.worksheet.table import Table

OUT = Path(__file__).resolve().parents[1] / "samples" / "generator-sample.xlsx"

CODES = {  # code: (range, voltage, construction)
    "R230 - Power - 2C+E - 1.5": ("R230", "LV", "CU-PVC (Power)"),
    "R230 - Power - 2C+E - 2.5": ("R230", "LV", "CU-PVC (Power)"),
    "R230 - Power - 2C+E - 4": ("R230", "LV", "CU-PVC (Power)"),
    "R400 - Power - 4C+E - 6": ("R400", "LV", "CU-XLPE (Power)"),
    "R400 - Power - 4C+E - 16": ("R400", "LV", "CU-XLPE (Power)"),
}
PARENTS = [("100-LB01", "NORTH YARD LIGHTING BOARD"), ("200-LB02", "WORKSHOP LIGHTING BOARD"),
           ("300-DB01", "ADMIN DISTRIBUTION BOARD")]
CONFIG = [
    ("KeyPlaceholder", "<<Key>>"), ("RunPlaceholder", "<<RUN>>"), ("LockedPlaceholder", "<<LOCKED>>"),
    ("StopAtBlankKey", "False"), ("BlankRowBetweenRuns", "True"), ("ParentSheet", "Parents"),
    ("ParentIncludeTag", "False"), ("CollapseSpaces", "True"), ("ReplaceFEquals", "True"),
    ("FreezeFormulas", "True"), ("RunFrom", "0"), ("RunUpTo", "1000"), ("KeepPrev", "True"),
    ("DiffKey", "Cable Number"), ("RunColumn", "Run Num"), ("DocNumber", ""), ("DocTitle", "Demo Lighting Cable Schedule"),
    ("DocRevision", ""),
]
LABELS = ["Template", "Standard", "Run", "From", "Area", "Destination", "To Tag", "Length", "Length each",
          "Qty", "Circuit", "Circuit No", "Size", "Size loop", "Locked"]
TAGS = ["<<Key>>", "<<Standard>>", "<<RUN>>", "<<FromTag>>", "<<Area>>", "<<ToDesc>>", "<<ToTag>>", "<<LEN>>",
        "<<LEN2>>", "<<Qty>>", "<<CCT1>>", "<<CCT2>>", "<<Size>>", "<<Size2>>", "<<LOCKED>>"]
RUNS = [
    [20, "Light fittings", 1, "100-LB01", "100", "NORTH YARD FLOODLIGHTS", None, 60, 12, 4, "L", 1, 2.5, 2.5, None],
    [20, "Light fittings", 2, "100-LB01", "100", "NORTH YARD WALKWAY LIGHTS", None, 45, 10, 6, "L", 2, 2.5, 1.5, None],
    [10, "Socket outlet", 3, "200-LB02", "200", "WORKSHOP BENCH OUTLETS", "200-SO01", 25, None, None, "P", 1, 2.5, None, None],
    [10, "Socket outlet", 4, "200-LB02", "200", "WORKSHOP WALL OUTLETS", "200-SO02", 30, None, None, "P", 2, 4, None, None],
    [40, "Exit sign", 5, "200-LB02", "200", "WORKSHOP EXIT SIGNS", None, 35, 8, 3, "E", 1, 1.5, 1.5, None],
    ["nr", "Spare", 6, "200-LB02", "200", "SPARE", None, None, None, None, None, None, None, None, None],
    [30, "Panel feed", 7, "300-DB01", "300", "ADMIN AIR CONDITIONING", "300-AC01", 50, None, None, "M", 1, 6, None, None],
    [30, "Panel feed", 8, "300-DB01", "300", "ADMIN WORKSHOP HOIST", "300-HS01", 70, None, None, "M", 2, 16, None, None],
    [99, "Not built yet", 9, "300-DB01", "300", "FUTURE LOAD", None, 20, None, None, "M", 3, 2.5, None, None],
    [20, "Light fittings", 10, "300-DB01", "300", "ADMIN CAR PARK LIGHTS", None, 80, 15, 5, "L", 3, 4, 2.5, None],
]
HEAD = ["TEMPLATE", "Seq", "Description", "Run Num", "Cable Number", "From", "From Location", "To", "To Location",
        "Length", "Cable Range", "Cable Type", "Cores", "Size", "Cable Code", "Code Check", "Voltage", "Type"]


def formulas(r: int) -> list[str]:  # columns O..R
    return [f'=K{r}&" - "&L{r}&" - "&M{r}&" - "&N{r}',
            f"=EXACT(VLOOKUP(O{r},Codes!A:A,1),O{r})",
            f'=IF(P{r}<>"",VLOOKUP(O{r},CableTypes!A:D,3,0),"")',
            f'=IF(P{r}<>"",VLOOKUP(O{r},CableTypes!A:D,4,0),"")']


CN = "<<FromTag_S>>-<<CCT1>><<CCT2>>"
TEMPLATES = [  # (id, seq, description, cable number, from, from loc, to, to loc, length, range, type, cores, size)
    (10, 1, "Socket outlet", f"{CN}-P1", "<<FromTag>>", "<<FromTag_P>>", "<<ToTag>>", "<<ToDesc>>", "<<LEN>>",
     "R230", "Power", "2C+E", "<<Size>>"),
    (20, 1, "Light fittings", f"{CN}-P1", "<<FromTag>>", "<<FromTag_P>>", "<<Area>> AREA",
     f"<<ToDesc>> JUNCTION BOX {CN}-JB1", "<<LEN>>", "R230", "Power", "2C+E", "<<Size>>"),
    (20, 2, "Light fittings", f'F="{CN}-P2 to P"& <<QTY>>+1', "<<Area>> AREA", f"<<ToDesc>> JUNCTION BOX {CN}-JB1",
     "<<Area>> AREA", "<<ToDesc>>  (<<QTY>> FITTINGS, *NOMINAL <<LEN2>>m EACH)", "F=<<LEN2>>*<<QTY>>",
     "R230", "Power", "2C+E", "<<Size2>>"),
    (30, 1, "Panel feed", f"{CN}-P1", "<<FromTag>>", "<<FromTag_P>>", "<<ToTag>>", "<<ToDesc>>", "<<LEN>>",
     "R400", "Power", "4C+E", "<<Size>>"),
    (40, 1, "Exit sign", f"{CN}-P1", "<<FromTag>>", "<<FromTag_P>>", "<<Area>> AREA", "<<ToDesc>>", "<<LEN>>",
     "R230", "Power", "2C+E", "<<Size>>"),
    (40, 2, "Exit sign", f'F="{CN}-P2 to P"& <<QTY>>', "<<Area>> AREA", "<<ToDesc>>", "<<Area>> AREA",
     "<<ToDesc>> (<<QTY>> SIGNS)", "F=<<LEN2>>*(<<QTY>>-1)", "R230", "Power", "2C+E", "<<Size2>>"),
]


def write(path: Path = OUT) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "Config"
    ws.append(["Setting", "Value", "Description"])
    for k, v in CONFIG:
        ws.append([k, v, ""])
    ws.add_table(Table(displayName="tblConfig", ref=f"A1:C{ws.max_row}"))
    ws["E1"], ws["F1"], ws["G1"], ws["H1"] = "Name", "Source", "Transform", "Default"
    ws["E2"], ws["F2"], ws["G2"] = "<<AREA_UP>>", "<<Area>>", "upper"
    ws.add_table(Table(displayName="tblPlaceholders", ref="E1:H2"))

    rs = wb.create_sheet("RunSheet")
    rs.append([None, *LABELS])
    rs.append([None, *TAGS])
    for r in RUNS:
        rs.append([None, *r])
    rs.add_table(Table(displayName="tblRunSheet", ref=f"B2:{chr(ord('A') + len(TAGS))}{rs.max_row}"))

    t = wb.create_sheet("Templates")
    t.append(HEAD)
    for k, row in enumerate(TEMPLATES, start=2):
        tid, seq, desc, cn, fr, frl, to, tol, ln, rng, typ, cores, size = row
        t.append([tid, seq, desc, "<<RUN>>", cn, fr, frl, to, tol, ln, rng, typ, cores, size, *formulas(k)])
    t.add_table(Table(displayName="tblTemplates", ref=f"A1:R{t.max_row}"))

    p = wb.create_sheet("Parents")
    p.append([None, "ParentEquipmentTag", "Description"])
    for tag, desc in PARENTS:
        p.append([None, tag, desc])
    p.add_table(Table(displayName="tblParents", ref=f"B1:C{p.max_row}"))

    c = wb.create_sheet("Codes")
    for code in sorted(CODES, key=str.lower):
        c.append([code])
    ct = wb.create_sheet("CableTypes")
    ct.append(["Code", "Range", "Voltage", "Type"])
    for code, (rng, volt, typ) in CODES.items():
        ct.append([code, rng, volt, typ])
    o = wb.create_sheet("Output")
    o.append(HEAD)
    for ws in wb.worksheets:
        for cell in ws[1]:
            cell.font = Font(bold=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


if __name__ == "__main__":
    print(write(Path(sys.argv[1]) if len(sys.argv) > 1 else OUT))
