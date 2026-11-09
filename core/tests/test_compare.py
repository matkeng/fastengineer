# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
from __future__ import annotations

import io
from pathlib import Path

import pytest
from openpyxl import Workbook as XlWorkbook
from openpyxl.styles import Font

from workbench_core.excel import CompareOptions, Workbook, compare_tables

SAMPLES = Path(__file__).resolve().parents[2] / "samples"


def _table(rows: list[list], struck_rows: tuple[int, ...] = (), struck_cells: tuple[str, ...] = (),
           key: int = 0):
    xl = XlWorkbook()
    ws = xl.active
    for r in rows:
        ws.append(r)
    for r in struck_rows:
        for c in ws[r]:
            c.font = Font(strike=True)
    for ref in struck_cells:
        ws[ref].font = Font(strike=True)
    buf = io.BytesIO()
    xl.save(buf)
    return Workbook(buf.getvalue(), "t.xlsx", "t").extract("sheet:Sheet", 1, key)


def _by_key(result):
    return {r.key: r for r in result.rows}


def test_row_statuses_and_order_independence() -> None:
    a = _table([["Tag", "kW", "Note"], ["P-1", 30, "x"], ["P-2", 15, "y"], ["P-3", 7, "z"],
                ["P-4", 5, "gone"]], struck_rows=(5,))
    b = _table([["Note", "Tag", "kW"],  # columns in a different order too
                ["new", "P-9", 1], ["z", "P-3", 7], ["x", "P-1", 37], ["gone", "P-4", 5]], key=1)
    r = compare_tables(a, b)
    rows = _by_key(r)
    assert rows["P-1"].status == "changed"
    assert rows["P-2"].status == "deleted" and rows["P-2"].b_row is None
    assert rows["P-3"].status == "unchanged"
    assert rows["P-4"].status == "restored"
    assert rows["P-9"].status == "added" and rows["P-9"].a_row is None
    kw = next(i for i, c in enumerate(r.columns) if c.name == "kW")
    assert rows["P-1"].cells[kw].change == "value"
    assert rows["P-1"].changed_cells == 1
    assert r.summary.model_dump() | {} == {
        "added": 1, "deleted": 1, "struck": 0, "restored": 1, "changed": 1, "unchanged": 1,
        "changed_cells": 1, "columns_added": 0, "columns_deleted": 0}


def test_struck_row_and_strike_only_change() -> None:
    a = _table([["Tag", "To"], ["C-1", "M-1"], ["C-2", "M-2"]])
    b = _table([["Tag", "To"], ["C-1", "M-1"], ["C-2", "M-2"]], struck_rows=(2,), struck_cells=("B3",))
    rows = _by_key(compare_tables(a, b))
    assert rows["C-1"].status == "struck"
    assert rows["C-1"].changed_cells == 0  # strike is implied by the row status
    assert rows["C-2"].status == "changed"
    assert rows["C-2"].cells[1].change == "strike"
    no_strike = _by_key(compare_tables(a, b, CompareOptions(compare_strike=False)))
    assert no_strike["C-2"].status == "unchanged"


def test_key_cell_struck_marks_row_deleted() -> None:
    a = _table([["Tag", "To"], ["C-1", "M-1"]])
    b = _table([["Tag", "To"], ["C-1", "M-1"]], struck_cells=("A2",))
    assert compare_tables(a, b).rows[0].status == "struck"


def test_columns_added_deleted_and_numbers() -> None:
    a = _table([["Tag", "Len", "Size"], ["C-1", 10, 2.50]])
    b = _table([["Tag", "Size", "Gland"], ["C-1", 2.5, "CW20"]])
    r = compare_tables(a, b)
    status = {c.name: c.status for c in r.columns}
    assert status == {"Tag": "same", "Size": "same", "Gland": "added", "Len": "deleted"}
    assert r.rows[0].status == "unchanged"  # 2.50 == 2.5; added/removed columns aren't cell changes
    assert r.columns[0].is_key


def test_case_and_whitespace_handling() -> None:
    a = _table([["Tag", "Desc"], ["p-1", "Feed  pump"]])
    b = _table([["TAG", "desc"], ["P-1", "feed pump"]])
    assert compare_tables(a, b).rows[0].status == "unchanged"
    strict = compare_tables(a, b, CompareOptions(ignore_case=False))
    assert {r.status for r in strict.rows} == {"added", "deleted"}


def test_duplicate_keys_pair_in_order() -> None:
    a = _table([["Tag", "To"], ["D", "1"], ["D", "2"]])
    b = _table([["Tag", "To"], ["D", "1"], ["D", "3"], ["D", "4"]])
    r = compare_tables(a, b)
    assert [x.status for x in r.rows] == ["unchanged", "changed", "added"]
    assert all(x.duplicate_key for x in r.rows)
    assert "D" in r.warnings[0]


@pytest.mark.skipif(not (SAMPLES / "cable-schedule-sample-revD.xlsx").exists(), reason="samples missing")
def test_sample_rev_c_to_rev_d() -> None:
    def load(name: str):
        wb = Workbook((SAMPLES / name).read_bytes(), name, name)
        return wb.extract("sheet:Cable Schedule", 4, 0, header_rows=2)

    r = compare_tables(load("cable-schedule-sample.xlsx"), load("cable-schedule-sample-revD.xlsx"))
    s = r.summary
    assert (s.added, s.deleted, s.struck, s.restored, s.changed) == (1, 1, 1, 1, 4)
    assert (s.columns_added, s.columns_deleted) == (1, 1)
    rows = _by_key(r)
    assert rows["CB-0413"].status == "added"
    assert rows["CB-0406"].status == "deleted"
    assert rows["CB-0403"].status == "struck"
    assert rows["CB-0404"].status == "restored"
    to = next(i for i, c in enumerate(r.columns) if c.name == "To")
    assert rows["CB-0410"].cells[to].change == "strike"
    assert rows["CB-0407"].cells[to].change == "both"  # "~~F-301~~ F-302" -> "F-302"


def test_export_xlsx() -> None:
    from openpyxl import load_workbook
    from openpyxl.cell.rich_text import CellRichText

    from workbench_core.excel import compare_to_xlsx

    a = _table([["Tag", "kW", "Note"], ["P-1", 30, "x"], ["P-2", 15, "y"]])
    b = _table([["Tag", "kW", "Gland"], ["P-1", 37, "CW20"], ["P-3", 5, "CW20"]], struck_cells=("A3",))
    r = compare_tables(a, b)
    wb = load_workbook(io.BytesIO(compare_to_xlsx(r)), rich_text=True)
    assert wb.sheetnames == ["Differences", "Cell changes", "Summary"]
    ws = wb["Differences"]
    header = [c.value for c in ws[1]]
    assert header == ["Status", "Tag", "kW", "Gland (new column)", "Note (removed column)",
                      "Changed cells", "Old row", "New row"]
    rows = {ws.cell(row=i, column=2).value: i for i in range(2, ws.max_row + 1)}
    p1 = rows["P-1"]
    assert ws.cell(row=p1, column=1).value == "Changed"
    diff = ws.cell(row=p1, column=3).value
    assert isinstance(diff, CellRichText) and str(diff) == "30  →  37"
    assert ws.cell(row=rows["P-3"], column=1).value == "Added"
    assert ws.cell(row=rows["P-3"], column=2).font.strike  # source strikethrough kept
    assert ws.cell(row=rows["P-2"], column=1).value == "Deleted"
    assert wb["Cell changes"].max_row == 2  # one changed cell

    only_added = load_workbook(io.BytesIO(compare_to_xlsx(r, statuses={"added"}, columns=[0, 1])))
    d = only_added["Differences"]
    assert d.max_row == 2 and [c.value for c in d[1]][:3] == ["Status", "Tag", "kW"]
