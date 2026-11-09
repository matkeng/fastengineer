from __future__ import annotations

import io
from pathlib import Path

import pytest
from openpyxl import Workbook as XlWorkbook
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont
from openpyxl.styles import Font

from workbench_core.excel import ExcelError, Workbook

SAMPLE = Path(__file__).resolve().parents[2] / "samples" / "cable-schedule-sample.xlsx"


def _load(xl: XlWorkbook, name: str = "t.xlsx") -> Workbook:
    buf = io.BytesIO()
    xl.save(buf)
    return Workbook(buf.getvalue(), name, "test")


@pytest.fixture
def small() -> Workbook:
    xl = XlWorkbook()
    ws = xl.active
    ws.title = "Data"
    ws.append(["Title row"])
    ws.append([])
    ws.append(["Tag", "Desc", "kW"])
    ws.append(["P-1", "Pump", 30])
    ws.append(["P-2", "Old pump", 15])
    ws.append(["P-3", None, 7.5])
    ws.append([None, "orphan", 1])
    ws.append(["P-1", "Dup", 2])
    for c in ws[5]:
        c.font = Font(strike=True)
    ws["B6"] = CellRichText(["new ", TextBlock(InlineFont(strike=True), "old")])
    ws.merge_cells("B7:B8")  # B8 takes B7's value "orphan"
    return _load(xl)


def test_header_suggestion(small: Workbook) -> None:
    pv = small.preview("sheet:Data")
    assert pv.suggested_header_row == 3
    assert pv.suggested_header_rows == 1


def test_merged_cells_are_expanded(small: Workbook) -> None:
    ex = small.extract("sheet:Data", header_row=3, key_column=0)
    by_row = {r.row: r for r in ex.rows}
    assert by_row[8].cells[1].t == "orphan" and by_row[8].cells[1].m
    assert not by_row[4].cells[1].m
    assert by_row[6].cells[1].s == "partial" and by_row[6].strike == "partial"


def test_strike_full_and_row_level(small: Workbook) -> None:
    ex = small.extract("sheet:Data", header_row=3, key_column=0)
    row5 = next(r for r in ex.rows if r.row == 5)
    assert row5.strike == "full"
    assert all(c.s == "full" for c in row5.cells)


def test_partial_strike_runs() -> None:
    xl = XlWorkbook()
    ws = xl.active
    ws.append(["Tag", "Note"])
    ws.append(["A", CellRichText(["keep ", TextBlock(InlineFont(strike=True), "gone"), " more"])])
    ws.append(["B", CellRichText([TextBlock(InlineFont(strike=True), "all struck")])])
    ex = _load(xl).extract("sheet:Sheet", header_row=1, key_column=0)
    a, b = ex.rows
    assert a.cells[1].s == "partial"
    assert [(r.text, r.strike) for r in a.cells[1].runs] == [
        ("keep ", False), ("gone", True), (" more", False)]
    assert a.strike == "partial"
    assert b.cells[1].s == "full" and b.cells[1].runs is None


def test_run_formatting_overrides_cell_font() -> None:
    # LibreOffice saves a struck first run's font as the cell font too; the
    # unstruck second run must still count as not struck.
    xl = XlWorkbook()
    ws = xl.active
    ws.append(["Tag", "To"])
    ws.append(["A", CellRichText([TextBlock(InlineFont(strike=True), "F-301"),
                                  TextBlock(InlineFont(), " F-302")])])
    ws["B2"].font = Font(strike=True)
    cell = _load(xl).extract("sheet:Sheet", header_row=1, key_column=0).rows[0].cells[1]
    assert cell.s == "partial"
    assert [(r.text, r.strike) for r in cell.runs] == [("F-301", True), (" F-302", False)]


def test_blank_keys_and_duplicates(small: Workbook) -> None:
    ex = small.extract("sheet:Data", header_row=3, key_column=0)
    assert ex.blank_keys_skipped == 1
    assert ex.duplicate_keys == ["P-1"]
    assert [r.duplicate_key for r in ex.rows if r.key == "P-1"] == [True, True]
    kept = small.extract("sheet:Data", header_row=3, key_column=0, skip_blank_keys=False)
    assert len(kept.rows) == len(ex.rows) + 1


def test_unsupported_and_bad_header(small: Workbook) -> None:
    with pytest.raises(ExcelError):
        Workbook(b"x", "old.xls", "id")
    with pytest.raises(ExcelError):
        small.columns("sheet:Data", header_row=99)


def test_missing_cached_formula_values_warn() -> None:
    xl = XlWorkbook()
    ws = xl.active
    ws.append(["Tag", "Value"])
    ws.append(["A", "=1+1"])  # openpyxl never stores a calculated result
    assert "formula" in _load(xl).summary().warnings[0]


@pytest.mark.skipif(not SAMPLE.exists(), reason="sample workbook not generated")
def test_sample_workbook() -> None:
    wb = Workbook(SAMPLE.read_bytes(), SAMPLE.name, "s")
    ids = [s.id for s in wb.summary().sources]
    assert ids == ["sheet:Cable Schedule", "sheet:IO List", "table:tblIO"]
    assert wb.summary().warnings == []

    pv = wb.preview("sheet:Cable Schedule")
    assert (pv.suggested_header_row, pv.suggested_header_rows) == (4, 2)
    cols = wb.columns("sheet:Cable Schedule", 4, 2)
    assert [c.name for c in cols.columns][3:5] == ["Cable Size (mm²)", "Cable Cores"]
    assert cols.suggested_key == 0

    ex = wb.extract("sheet:Cable Schedule", 4, 0, header_rows=2)
    rows = {r.key: r for r in ex.rows if not r.duplicate_key}
    assert rows["CB-0401"].cells[7].v == pytest.approx(50.9)  # calculated formula value
    assert rows["CB-0404"].strike == "full"
    assert rows["CB-0402"].cells[8].s == "partial"
    assert rows["CB-0407"].cells[2].s == "partial"  # struck F-301, new F-302
    assert rows["CB-0402"].cells[1].m  # merged "From" cell
    assert ex.duplicate_keys == ["CB-0412"]
