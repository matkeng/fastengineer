# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Generate synthetic sample workbooks for the Excel query and compare features:

  samples/cable-schedule-sample.xlsx       Rev C: title rows above a two-row merged
                                           header, merged cells, struck-out and
                                           partly struck cells, formulas, and an
                                           Excel table on a second sheet.
  samples/cable-schedule-sample-revD.xlsx  Rev D of the same schedule, rows in a
                                           different order, with every kind of change
                                           for the compare feature (see REV_D below).

Formula results are only stored in a file once a spreadsheet app has
calculated it, so if LibreOffice is installed the files are recalculated with it:

    python scripts/make_sample_workbook.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from openpyxl import Workbook
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

SAMPLES = Path(__file__).resolve().parents[1] / "samples"
STRIKE = Font(strike=True)
HEAD = Font(bold=True)
FILL = PatternFill("solid", fgColor="DDE4EE")


def struck(text: str) -> CellRichText:
    return CellRichText([TextBlock(InlineFont(strike=True), text)])


# Columns: (top header, sub header). "Cable" spans Size and Cores.
COLUMNS_C = [("Cable Tag", None), ("From", None), ("To", None), ("Cable", "Size (mm²)"),
             ("Cable", "Cores"), ("Length (m)", None), ("Load (kW)", None),
             ("Current (A)", None), ("Remarks", None)]

# Rev C rows. "STRIKE_ROW" marks a fully struck-out (deleted) row.
REV_C = [
    {"Cable Tag": "CB-0401", "From": "MCC-01", "To": "P-101", "Size (mm²)": 16, "Cores": 4, "Length (m)": 85, "Load (kW)": 30, "Remarks": "Feed pump"},
    {"Cable Tag": "CB-0402", "From": "MCC-01", "To": "P-102", "Size (mm²)": 16, "Cores": 4, "Length (m)": 92, "Load (kW)": 30,
     "Remarks": CellRichText(["Size ", TextBlock(InlineFont(strike=True), "16"), " 25 mm² per RFI-12"])},
    {"Cable Tag": "CB-0403", "From": "MCC-01", "To": "M-204", "Size (mm²)": 4, "Cores": 4, "Length (m)": 40, "Load (kW)": 7.5},
    {"Cable Tag": "CB-0404", "From": "MCC-01", "To": "AG-01", "Size (mm²)": 2.5, "Cores": 4, "Length (m)": 55, "Load (kW)": 2.2, "Remarks": "Removed in Rev C", "STRIKE_ROW": True},
    {"Cable Tag": "CB-0405", "From": "MCC-02", "To": "P-201", "Size (mm²)": 25, "Cores": 4, "Length (m)": 130, "Load (kW)": 45, "STRIKE": ["Length (m)"]},
    {"Cable Tag": "CB-0406", "From": "MCC-02", "To": "P-202", "Size (mm²)": 25, "Cores": 4, "Length (m)": 128, "Load (kW)": 45},
    {"Cable Tag": "CB-0407", "From": "MCC-02", "To": CellRichText([TextBlock(InlineFont(strike=True), "F-301"), " F-302"]), "Size (mm²)": 6, "Cores": 4, "Length (m)": 70, "Load (kW)": 11},
    {"Cable Tag": "CB-0408", "From": "DB-01", "To": "LT-01", "Size (mm²)": 2.5, "Cores": 3, "Length (m)": 30, "Load (kW)": 1.5, "Remarks": "Lighting"},
    {"Cable Tag": "CB-0409", "From": "DB-01", "To": "LT-02", "Size (mm²)": 2.5, "Cores": 3, "Length (m)": 35, "Load (kW)": 1.5, "Remarks": "Lighting"},
    {"Cable Tag": "CB-0410", "From": "DB-01", "To": "SO-01", "Size (mm²)": 4, "Cores": 3, "Length (m)": 25, "Load (kW)": 3},
    {"Remarks": "Spare ways below"},
    {"Cable Tag": "CB-0411", "From": "MCC-02", "To": "C-401", "Size (mm²)": 35, "Cores": 4, "Length (m)": 150, "Load (kW)": 55},
    {"Cable Tag": "CB-0412", "From": "MCC-02", "To": "C-402", "Size (mm²)": 35, "Cores": 4, "Length (m)": 150, "Load (kW)": 55, "Remarks": "Duplicate tag - check"},
    {"Cable Tag": "CB-0412", "From": "MCC-03", "To": "C-403", "Size (mm²)": 35, "Cores": 4, "Length (m)": 160, "Load (kW)": 55, "Remarks": "Duplicate tag - check"},
]

# Rev D: "Length (m)" column removed, "Gland Type" column added, rows re-sorted by "To".
COLUMNS_D = [("Cable Tag", None), ("From", None), ("To", None), ("Cable", "Size (mm²)"),
             ("Cable", "Cores"), ("Load (kW)", None), ("Current (A)", None),
             ("Gland Type", None), ("Remarks", None)]
REV_D = [
    # value changes
    {"Cable Tag": "CB-0401", "From": "MCC-01", "To": "P-101", "Size (mm²)": 16, "Cores": 4, "Load (kW)": 37, "Gland Type": "CW20", "Remarks": "Feed pump - motor upsized"},
    {"Cable Tag": "CB-0402", "From": "MCC-01", "To": "P-102", "Size (mm²)": 25, "Cores": 4, "Load (kW)": 30, "Gland Type": "CW25", "Remarks": "Size per RFI-12"},
    # now struck out (deleted by markup)
    {"Cable Tag": "CB-0403", "From": "MCC-01", "To": "M-204", "Size (mm²)": 4, "Cores": 4, "Load (kW)": 7.5, "Gland Type": "CW20", "Remarks": "Deleted Rev D", "STRIKE_ROW": True},
    # no longer struck out (restored)
    {"Cable Tag": "CB-0404", "From": "MCC-01", "To": "AG-01", "Size (mm²)": 2.5, "Cores": 4, "Load (kW)": 2.2, "Gland Type": "CW20", "Remarks": "Reinstated Rev D"},
    {"Cable Tag": "CB-0405", "From": "MCC-02", "To": "P-201", "Size (mm²)": 25, "Cores": 4, "Load (kW)": 45, "Gland Type": "CW25"},
    # CB-0406 removed entirely
    {"Cable Tag": "CB-0407", "From": "MCC-02", "To": "F-302", "Size (mm²)": 6, "Cores": 4, "Load (kW)": 11, "Gland Type": "CW20"},
    {"Cable Tag": "CB-0408", "From": "DB-01", "To": "LT-01", "Size (mm²)": 2.5, "Cores": 3, "Load (kW)": 1.5, "Gland Type": "CW20", "Remarks": "Lighting"},
    {"Cable Tag": "CB-0409", "From": "DB-01", "To": "LT-02", "Size (mm²)": 2.5, "Cores": 3, "Load (kW)": 1.5, "Gland Type": "CW20", "Remarks": "Lighting"},
    # strike-only change: "To" struck, same text
    {"Cable Tag": "CB-0410", "From": "DB-01", "To": "SO-01", "Size (mm²)": 4, "Cores": 3, "Load (kW)": 3, "Gland Type": "CW20", "STRIKE": ["To"]},
    {"Cable Tag": "CB-0411", "From": "MCC-02", "To": "C-401", "Size (mm²)": 35, "Cores": 4, "Load (kW)": 55, "Gland Type": "CW32"},
    {"Cable Tag": "CB-0412", "From": "MCC-02", "To": "C-402", "Size (mm²)": 35, "Cores": 4, "Load (kW)": 55, "Gland Type": "CW32", "Remarks": "Duplicate tag - check"},
    {"Cable Tag": "CB-0412", "From": "MCC-03", "To": "C-403", "Size (mm²)": 35, "Cores": 4, "Load (kW)": 55, "Gland Type": "CW32", "Remarks": "Duplicate tag - check"},
    # added
    {"Cable Tag": "CB-0413", "From": "MCC-03", "To": "P-301", "Size (mm²)": 10, "Cores": 4, "Load (kW)": 15, "Gland Type": "CW20", "Remarks": "New in Rev D"},
]
REV_D.sort(key=lambda r: str(r["To"]))  # a different row order on purpose


def cable_sheet(ws, title: str, rev_note: str, columns, rows) -> None:
    ws["A1"] = title
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = rev_note
    ncol = len(columns)
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncol)

    for col, (top, sub) in enumerate(columns, start=1):
        for row, val in ((4, top), (5, sub)):
            c = ws.cell(row=row, column=col, value=val)
            c.font, c.fill = HEAD, FILL
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    col = 1
    while col <= ncol:  # merge equal top headers across, single headers down
        top, sub = columns[col - 1]
        span = 1
        while col + span <= ncol and columns[col + span - 1][0] == top and columns[col + span - 1][1]:
            span += 1
        if span > 1:
            for c in range(col + 1, col + span):
                ws.cell(row=4, column=c).value = None
            ws.merge_cells(start_row=4, start_column=col, end_row=4, end_column=col + span - 1)
        elif sub is None:
            ws.merge_cells(start_row=4, start_column=col, end_row=5, end_column=col)
        col += span

    names = [sub or top for top, sub in columns]
    letter = {n: get_column_letter(i + 1) for i, n in enumerate(names)}
    for i, data in enumerate(rows):
        r = 6 + i
        for name in names:
            if name in data:
                ws[f"{letter[name]}{r}"] = data[name]
        if "Load (kW)" in data and "Current (A)" in letter:
            # 400 V three-phase, pf 0.85: I = P / (sqrt(3) * V * pf)
            ws[f"{letter['Current (A)']}{r}"] = f"=ROUND({letter['Load (kW)']}{r}*1000/(SQRT(3)*400*0.85),1)"
        if data.get("STRIKE_ROW"):
            for c in range(1, ncol + 1):
                ws.cell(row=r, column=c).font = STRIKE
        for name in data.get("STRIKE", []):
            ws[f"{letter[name]}{r}"].font = STRIKE
    ws.column_dimensions["A"].width = 12
    ws.column_dimensions[letter["Remarks"]].width = 32


def rev_c() -> Workbook:
    wb = Workbook()
    ws = wb.active
    ws.title = "Cable Schedule"
    cable_sheet(ws, "SAMPLE PLANT - CABLE SCHEDULE (synthetic data)",
                "Rev C - struck-through entries are deleted", COLUMNS_C, REV_C)
    ws.merge_cells("B6:B7")  # merged cells in the body: same source for two cables

    io = wb.create_sheet("IO List")
    io.append(["Tag", "Description", "Signal", "Range", "Card", "Channel"])
    for r in [
        ("FT-1001", "Feed flow", "AI", "0-50 m³/h", "AI-01", 1),
        ("PT-1002", "Pump discharge pressure", "AI", "0-10 bar", "AI-01", 2),
        ("LT-1003", "Tank level", "AI", "0-100 %", "AI-01", 3),
        ("XS-1004", "Pump running", "DI", None, "DI-01", 1),
        ("XY-1005", "Pump start", "DO", None, "DO-01", 1),
        ("TT-1006", "Bearing temperature", "AI", "0-150 °C", "AI-01", 4),
    ]:
        io.append(r)
    io["A6"].font = STRIKE
    io["B6"].font = STRIKE
    t = Table(displayName="tblIO", ref="A1:F7")
    t.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
    io.add_table(t)
    return wb


def rev_d() -> Workbook:
    wb = Workbook()
    ws = wb.active
    ws.title = "Cable Schedule"
    cable_sheet(ws, "SAMPLE PLANT - CABLE SCHEDULE (synthetic data)",
                "Rev D - struck-through entries are deleted", COLUMNS_D, REV_D)
    return wb


def save(wb: Workbook, out: Path) -> None:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        wb.save(out)
        print(f"Wrote {out} (no LibreOffice: formula results not calculated)", file=sys.stderr)
        return
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "in" / out.name
        raw.parent.mkdir()
        wb.save(raw)
        # Round-trip through LibreOffice so formula results are stored.
        subprocess.run(
            [soffice, "--headless", "--calc", "--convert-to", "xlsx:Calc MS Excel 2007 XML",
             "--outdir", str(Path(tmp) / "out"), str(raw)],
            check=True, capture_output=True, timeout=180,
        )
        shutil.copy(Path(tmp) / "out" / out.name, out)
    print(f"Wrote {out} (recalculated with LibreOffice)")


def main() -> None:
    SAMPLES.mkdir(parents=True, exist_ok=True)
    save(rev_c(), SAMPLES / "cable-schedule-sample.xlsx")
    save(rev_d(), SAMPLES / "cable-schedule-sample-revD.xlsx")


if __name__ == "__main__":
    main()
