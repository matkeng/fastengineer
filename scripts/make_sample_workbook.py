"""Generate samples/cable-schedule-sample.xlsx: synthetic test data for the
Excel query wizard (title rows above the header, a two-row merged header,
merged cells, struck-out and partly struck-out cells, formulas, an Excel table).

Formula results are only stored in a file once a spreadsheet app has
calculated it, so if LibreOffice is installed the file is recalculated with it:

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
from openpyxl.worksheet.table import Table, TableStyleInfo

OUT = Path(__file__).resolve().parents[1] / "samples" / "cable-schedule-sample.xlsx"
STRIKE = Font(strike=True)
HEAD = Font(bold=True)
FILL = PatternFill("solid", fgColor="DDE4EE")


def cable_schedule(wb: Workbook) -> None:
    ws = wb.active
    ws.title = "Cable Schedule"
    ws["A1"] = "SAMPLE PLANT - CABLE SCHEDULE (synthetic data)"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = "Rev C - struck-through entries are deleted"
    ws.merge_cells("A1:I1")

    # Two-row header: "Cable" spans Size and Cores (row 4); others merged down.
    top = ["Cable Tag", "From", "To", "Cable", None, "Length (m)", "Load (kW)", "Current (A)", "Remarks"]
    sub = [None, None, None, "Size (mm²)", "Cores", None, None, None, None]
    for col, (a, b) in enumerate(zip(top, sub), start=1):
        for row, val in ((4, a), (5, b)):
            c = ws.cell(row=row, column=col, value=val)
            c.font, c.fill = HEAD, FILL
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.merge_cells("D4:E4")
    for col in "ABCFGHI":
        ws.merge_cells(f"{col}4:{col}5")

    rows = [
        ("CB-0401", "MCC-01", "P-101", 16, 4, 85, 30, None, "Feed pump"),
        ("CB-0402", "MCC-01", "P-102", 16, 4, 92, 30, None, "Standby feed pump"),
        ("CB-0403", "MCC-01", "M-204", 4, 4, 40, 7.5, None, None),
        ("CB-0404", "MCC-01", "AG-01", 2.5, 4, 55, 2.2, None, "Removed in Rev C"),
        ("CB-0405", "MCC-02", "P-201", 25, 4, 130, 45, None, None),
        ("CB-0406", "MCC-02", "P-202", 25, 4, 128, 45, None, None),
        ("CB-0407", "MCC-02", "F-301", 6, 4, 70, 11, None, None),
        ("CB-0408", "DB-01", "LT-01", 2.5, 3, 30, 1.5, None, "Lighting"),
        ("CB-0409", "DB-01", "LT-02", 2.5, 3, 35, 1.5, None, "Lighting"),
        ("CB-0410", "DB-01", "SO-01", 4, 3, 25, 3, None, None),
        (None, None, None, None, None, None, None, None, "Spare ways below"),
        ("CB-0411", "MCC-02", "C-401", 35, 4, 150, 55, None, None),
        ("CB-0412", "MCC-02", "C-402", 35, 4, 150, 55, None, "Duplicate tag - check"),
        ("CB-0412", "MCC-03", "C-403", 35, 4, 160, 55, None, "Duplicate tag - check"),
    ]
    for i, r in enumerate(rows):
        row = 6 + i
        for col, v in enumerate(r, start=1):
            ws.cell(row=row, column=col, value=v)
        if r[6] is not None:
            # 400 V three-phase, pf 0.85: I = P / (sqrt(3) * V * pf)
            ws.cell(row=row, column=8, value=f"=ROUND(G{row}*1000/(SQRT(3)*400*0.85),1)")

    # Whole row struck out (deleted circuit).
    for col in range(1, 10):
        ws.cell(row=9, column=col).font = STRIKE
    # Partial strike: size changed from 16 to 25 written as rich text in Remarks,
    # and a struck-out "To" with the new tag next to it.
    ws["I7"] = CellRichText(["Size ", TextBlock(InlineFont(strike=True), "16"), " 25 mm² per RFI-12"])
    ws["C12"] = CellRichText([TextBlock(InlineFont(strike=True), "F-301"), " F-302"])
    # A single fully struck cell.
    ws["F10"].font = STRIKE
    # Merged cells in the body: same source for two cables.
    ws.merge_cells("B6:B7")

    ws.column_dimensions["A"].width = 12
    ws.column_dimensions["I"].width = 32


def io_list(wb: Workbook) -> None:
    ws = wb.create_sheet("IO List")
    header = ["Tag", "Description", "Signal", "Range", "Card", "Channel"]
    data = [
        ("FT-1001", "Feed flow", "AI", "0-50 m³/h", "AI-01", 1),
        ("PT-1002", "Pump discharge pressure", "AI", "0-10 bar", "AI-01", 2),
        ("LT-1003", "Tank level", "AI", "0-100 %", "AI-01", 3),
        ("XS-1004", "Pump running", "DI", None, "DI-01", 1),
        ("XY-1005", "Pump start", "DO", None, "DO-01", 1),
        ("TT-1006", "Bearing temperature", "AI", "0-150 °C", "AI-01", 4),
    ]
    ws.append(header)
    for r in data:
        ws.append(r)
    ws["A6"].font = STRIKE
    ws["B6"].font = STRIKE
    t = Table(displayName="tblIO", ref=f"A1:F{len(data) + 1}")
    t.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
    ws.add_table(t)


def main() -> None:
    wb = Workbook()
    cable_schedule(wb)
    io_list(wb)
    OUT.parent.mkdir(parents=True, exist_ok=True)

    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        wb.save(OUT)
        print(f"Wrote {OUT} (no LibreOffice: formula results not calculated)", file=sys.stderr)
        return
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "in" / OUT.name
        raw.parent.mkdir()
        wb.save(raw)
        # Round-trip through LibreOffice so formula results are stored.
        subprocess.run(
            [soffice, "--headless", "--calc", "--convert-to", "xlsx:Calc MS Excel 2007 XML",
             "--outdir", str(Path(tmp) / "out"), str(raw)],
            check=True, capture_output=True, timeout=180,
        )
        shutil.copy(Path(tmp) / "out" / OUT.name, OUT)
    print(f"Wrote {OUT} (recalculated with LibreOffice)")


if __name__ == "__main__":
    main()
