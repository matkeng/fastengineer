# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Bulk editing workbook: round trip, change preview, apply, errors (invented sample data)."""

import io
from pathlib import Path

import openpyxl
import pytest

from workbench_core.generators.bulk import Inputs, apply_inputs, read_inputs, resolve_card_type, write_inputs
from workbench_core.generators.expand import build
from workbench_core.generators.hardware import default_catalogue
from workbench_core.generators.xlsx_import import import_workbook

SAMPLE = Path(__file__).resolve().parents[2] / "samples" / "generator-sample.xlsx"


@pytest.fixture(scope="module")
def current() -> Inputs:
    return Inputs(generator=import_workbook(SAMPLE).generator)


def _wb(inp: Inputs):
    return openpyxl.load_workbook(io.BytesIO(write_inputs(inp, "Demo")))


def _bytes(wb) -> bytes:
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_every_input_table_has_a_sheet(current):
    wb = _wb(current)
    # (PLC cards and the card / rack types are in the PLC List's workbook now)
    assert wb.sheetnames == ["About", "RunSheet", "Templates", "Parents", "Derived tags", "Routes", "Cable prefixes",
                             "T CableTypes", "T Codes"]
    rs = wb["RunSheet"]
    assert rs["A1"].value == "Row ID" and rs["B2"].value == "<<Key>>" and rs["A3"].value == "3"
    t = wb["Templates"]
    assert t["A1"].value == "TEMPLATE" and t["O2"].value == "ƒ concat"
    assert t["E3"].data_type == "s" or not str(t["E3"].value).startswith("=")  # late formulas stay text


def test_unchanged_file_changes_nothing(current):
    pv, parsed = read_inputs(write_inputs(current), current)
    assert all(not (s.added or s.removed or s.changed or s.errors) for s in pv.sheets)
    again = apply_inputs(current, parsed, list(parsed))
    assert again.generator.model_dump() == current.generator.model_dump()


def test_edits_preview_and_apply(current):
    wb = _wb(current)
    rs = wb["RunSheet"]
    rs.append([None, 10, "Socket outlet", 99, "200-LB02", 200, "NEW OUTLETS", "200-SO09", 5, None, None, "P", 9, 2.5])
    rs["G3"] = "CHANGED DESC"
    rs.delete_rows(12)  # run 10 (row id 12)
    wb["Templates"]["E2"] = "<<FromTag_S>>-X<<CCT2>>"
    wb["Parents"].append(["400-DB01", "NEW BOARD"])
    wb["Routes"].append(["A", "B", 12.5])
    pv, parsed = read_inputs(_bytes(wb), current)
    s = {x.table: x for x in pv.sheets}
    assert (s["runsheet"].added, s["runsheet"].removed, s["runsheet"].changed) == (1, 1, 1)
    assert ("Destination", "NORTH YARD FLOODLIGHTS", "CHANGED DESC") in next(c for c in s["runsheet"].changes if c.kind == "changed").cells
    assert s["templates"].changed == 1 and s["parents"].added == 1 and s["routes"].added == 1
    assert s["runsheet"].notes == ["1 row(s) without a Row ID added as new runs"]
    new = apply_inputs(current, parsed, ["runsheet", "templates"])
    assert new.generator.parents == current.generator.parents  # not chosen: unchanged
    assert len(new.generator.runsheet.rows) == 10
    r = build(new.generator)
    cn = r.header.index("Cable Number")
    assert "200LB02-X9" in [row.cells[cn] for row in r.rows]  # edited template applied to the new run


def test_errors_are_per_sheet(current):
    wb = _wb(current)
    wb["RunSheet"]["A1"] = "Something else"
    wb.create_sheet("Notes")
    wb.create_sheet("PLC cards")  # a workbook from before the PLC List: its PLC sheets are left alone
    pv, parsed = read_inputs(_bytes(wb), current)
    s = {x.table: x for x in pv.sheets}
    assert "Row ID" in s["runsheet"].errors[0]
    assert "runsheet" not in parsed and "templates" in parsed
    assert pv.ignored_sheets == ["Notes", "PLC cards"]
    with pytest.raises(ValueError, match="Not an Excel workbook"):
        read_inputs(b"nope", current)


def test_removed_sheet_is_left_alone(current):
    wb = _wb(current)
    del wb["Templates"]
    pv, parsed = read_inputs(_bytes(wb), current)
    assert "templates" not in {x.table for x in pv.sheets} and "templates" not in parsed


def test_resolve_card_type():
    cat = default_catalogue()
    cat.card_types[3].part_number = "IB-16X"
    assert resolve_card_type("di16", cat) == "di16"
    assert resolve_card_type("IB-16X", cat) == "di16"
    assert resolve_card_type("DI 16", cat) == "di16" and resolve_card_type("rtd-8", cat) == "rtd8"
    assert resolve_card_type("Network", cat) == "net"
    assert resolve_card_type("DI 7", cat) is None and resolve_card_type("", cat) is None
