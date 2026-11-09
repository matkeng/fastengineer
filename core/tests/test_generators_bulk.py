# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Bulk editing workbook: round trip, change preview, apply, errors (invented sample data)."""

import io
from pathlib import Path

import openpyxl
import pytest

from workbench_core.generators.bulk import Inputs, apply_inputs, read_inputs, resolve_card_type, write_inputs
from workbench_core.generators.expand import build
from workbench_core.generators.hardware import Card, Hardware, Panel, Rack, default_catalogue
from workbench_core.generators.xlsx_import import import_workbook

SAMPLE = Path(__file__).resolve().parents[2] / "samples" / "generator-sample.xlsx"


@pytest.fixture(scope="module")
def current() -> Inputs:
    g = import_workbook(SAMPLE).generator
    hw = Hardware(panels=[Panel(tag="PCC-01", racks=[Rack(number=1, rack_type_id="rack", cards=[
        Card(card_type_id="net"), None, Card(card_type_id="di16", spare=True, notes="n")])])])
    return Inputs(generator=g, hardware=hw, catalogue=default_catalogue())


def _wb(inp: Inputs):
    return openpyxl.load_workbook(io.BytesIO(write_inputs(inp, "Demo")))


def _bytes(wb) -> bytes:
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_every_input_table_has_a_sheet(current):
    wb = _wb(current)
    assert wb.sheetnames == ["About", "RunSheet", "Templates", "Parents", "Derived tags", "Routes", "Cable prefixes",
                             "PLC cards", "Card types", "Rack types", "T CableTypes", "T Codes"]
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
    assert again.hardware.model_dump(exclude={"panels": {"__all__": {"id": True, "racks": {"__all__": {"id": True, "cards": {"__all__": {"id"}}}}}}}) == \
        current.hardware.model_dump(exclude={"panels": {"__all__": {"id": True, "racks": {"__all__": {"id": True, "cards": {"__all__": {"id"}}}}}}})


def test_edits_preview_and_apply(current):
    wb = _wb(current)
    rs = wb["RunSheet"]
    rs.append([None, 10, "Socket outlet", 99, "200-LB02", 200, "NEW OUTLETS", "200-SO09", 5, None, None, "P", 9, 2.5])
    rs["G3"] = "CHANGED DESC"
    rs.delete_rows(12)  # run 10 (row id 12)
    wb["Templates"]["E2"] = "<<FromTag_S>>-X<<CCT2>>"
    wb["Parents"].append(["400-DB01", "NEW BOARD"])
    wb["Routes"].append(["A", "B", 12.5])
    wb["PLC cards"].append(["PCC-01", None, None, 1, "rack", None, 1, 5, "DI-32X", None, None, None, "MYDI", "yes", None])
    wb["Card types"]["D5"] = "IB-16X"
    wb["Card types"]["D6"] = "DI-32X"  # di32
    pv, parsed = read_inputs(_bytes(wb), current)
    s = {x.table: x for x in pv.sheets}
    assert (s["runsheet"].added, s["runsheet"].removed, s["runsheet"].changed) == (1, 1, 1)
    assert ("Destination", "NORTH YARD FLOODLIGHTS", "CHANGED DESC") in next(c for c in s["runsheet"].changes if c.kind == "changed").cells
    assert s["templates"].changed == 1 and s["parents"].added == 1 and s["routes"].added == 1
    assert s["hardware"].added == 1 and s["card_types"].changed == 2
    assert s["runsheet"].notes == ["1 row(s) without a Row ID added as new runs"]
    new = apply_inputs(current, parsed, ["runsheet", "templates", "hardware", "card_types"])
    assert new.generator.parents == current.generator.parents  # not chosen: unchanged
    assert len(new.generator.runsheet.rows) == 10
    card = new.hardware.panels[0].racks[0].cards[4]
    assert card.card_type_id == "di32" and card.tag == "MYDI" and card.spare
    r = build(new.generator)
    cn = r.header.index("Cable Number")
    assert "200LB02-X9" in [row.cells[cn] for row in r.rows]  # edited template applied to the new run


def test_errors_are_per_sheet(current):
    wb = _wb(current)
    wb["RunSheet"]["A1"] = "Something else"
    wb["PLC cards"].append(["PCC-01", None, None, 1, "rack", None, 1, 3, "DI16"])  # slot 3 used twice
    wb["Card types"]["B2"] = "XX"
    wb.create_sheet("Notes")
    pv, parsed = read_inputs(_bytes(wb), current)
    s = {x.table: x for x in pv.sheets}
    assert "Row ID" in s["runsheet"].errors[0]
    assert "used twice" in s["hardware"].errors[0]
    assert "Kind must be one of" in s["card_types"].errors[0]
    assert "runsheet" not in parsed and "templates" in parsed
    assert pv.ignored_sheets == ["Notes"]
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
