# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Load types' component tables: a part per range of a load's field, reached as <<LoadType.CB.PartNumber>>."""

from __future__ import annotations

import pytest

from workbench_core.keylists.loadgen import LISTS, generate
from workbench_core.keylists.loadlist import LoadListRow
from workbench_core.keylists.validate import check_load_types
from workbench_core.keylists.workbooks import export_type_rows, read_component_tables, write_sheets
from workbench_core.refdata import RefValidationError

BASE = {"id": "t1", "code": "DOL", "name": "Direct on line", "rating_unit": "kW", "voltage": "415", "phases": "AC-3-phase"}
TABLES = [{"name": "CB", "columns": ["Part Number", "Frame"], "rows": [
              {"min": "0", "max": "7.5", "values": {"Part Number": "GV2-ME14", "Frame": "S"}},
              {"min": "7.5", "max": "", "values": {"Part Number": "GV3-P32", "Frame": "M"}}]},
          {"name": "Contactor", "match_field": "rated_current", "columns": ["Part Number"], "rows": [
              {"max": "18", "values": {"Part Number": "LC1D18"}}, {"min": "18", "max": "32", "values": {"Part Number": "LC1D32"}}]}]
ROWS = {"equipment_list": [{"Tag": "<<Tag>>", "Model": "<<LoadType.CB.PartNumber>> / <<LoadType.Contactor.Part Number|default:->>",
                            "Remarks": "<<LoadType.CB.Frame|lower>> <<LoadType.CB>>"}]}


def _load(key: str, rating, current=None) -> LoadListRow:
    return LoadListRow(recipe_id="m", key=key, source="MEL", target="MEL", load_type_id="t1",
                       values={"tag": key, "load_rating": rating, "rated_current": current})


def test_a_load_gets_the_row_its_rating_falls_in() -> None:
    types = check_load_types([BASE | {"components": TABLES, "rows": ROWS}])
    loads = [_load("P-1", 5.5, 11.2), _load("P-2", 7.5, 25), _load("P-3", 30, 55), _load("P-4", None)]
    out = generate("equipment_list", loads, {t.id: t for t in types.items}, {})
    cols = LISTS["equipment_list"].columns
    got = {r.cells[0]: dict(zip(cols, r.cells)) for r in out.rows}
    assert got["P-1"]["Model"] == "GV2-ME14 / LC1D18" and got["P-1"]["Remarks"] == "s GV2-ME14"
    assert got["P-2"]["Model"] == "GV2-ME14 / LC1D32"  # 7.5 is in the first range: the first row that fits wins
    assert got["P-3"]["Model"] == "GV3-P32 / -"  # no contactor for 55 A: blank, filled by default:
    assert got["P-4"]["Model"] == "/ -" and out.unresolved_count == 0  # no rating: nothing matches


def test_misspelt_tables_and_columns_are_reported() -> None:
    rows = {"equipment_list": [{"Tag": "<<Tag>>", "Model": "<<LoadType.Breaker.PartNumber>>", "Remarks": "<<LoadType.CB.Price>>"}]}
    types = check_load_types([BASE | {"components": TABLES, "rows": rows}])
    out = generate("equipment_list", [_load("P-1", 5.5)], {t.id: t for t in types.items}, {})
    assert out.unresolved_tokens == [
        "<<LoadType.Breaker.PartNumber>> ('Breaker' is not a component table of load type DOL (its tables: cb, contactor))",
        "<<LoadType.CB.Price>> ('Price' is not a column of the component table (its columns: partnumber, frame, min, max))"]


@pytest.mark.parametrize("table, field, message", [
    ({"name": "", "columns": ["P"]}, "name", "needs a name"),
    ({"name": "Code", "columns": ["P"]}, "name", "load type field's tag"),
    ({"name": "CB", "columns": []}, "columns", "at least one column"),
    ({"name": "CB", "columns": ["Min"]}, "columns", "Min and Max are the range"),
    ({"name": "CB", "columns": ["P"], "rows": [{"min": "x"}]}, "rows.0", "Min must be a number"),
    ({"name": "CB", "columns": ["P"], "rows": [{"min": "9", "max": "2"}]}, "rows.0", "Min is more than Max"),
    ({"name": "CB", "columns": ["P"], "rows": [{"values": {"Q": "1"}}]}, "rows.0", "not a column of the table: Q"),
])
def test_what_is_refused(table, field, message) -> None:
    with pytest.raises(RefValidationError) as exc:
        check_load_types([BASE | {"components": [table]}])
    assert message in exc.value.fields[f"t1.components.0.{field}"]


def test_two_tables_with_one_name_are_refused() -> None:
    with pytest.raises(RefValidationError) as exc:
        check_load_types([BASE | {"components": [{"name": "CB", "columns": ["P"]}, {"name": "c_b", "columns": ["P"]}]}])
    assert "Two tables are called c_b" in exc.value.fields["t1.components.1.name"]


def test_tables_round_trip_through_the_types_workbook() -> None:
    tables = check_load_types([BASE | {"components": TABLES}]).items[0].components
    sheets = export_type_rows({}, None, components=tables)
    assert dict(sheets)["Table CB"][:2] == [["Min load_rating", "Max load_rating", "Part Number", "Frame"], [0, 7.5, "GV2-ME14", "S"]]
    back = read_component_tables(write_sheets(sheets), tables)
    again = check_load_types([BASE | {"components": back}]).items[0].components
    assert [t.model_dump() for t in again] == [t.model_dump() for t in tables]
