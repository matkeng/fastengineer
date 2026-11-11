# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""One load type's or equipment type's rows as a workbook (keylists.workbooks)."""

from __future__ import annotations

import pytest

from workbench_core.keylists.loadgen import LISTS
from workbench_core.keylists.workbooks import export_type_rows, import_type_rows, read_sheets, write_sheets

ROWS = {"cable_schedule": [{"Cable Number": "<<Tag>>-P<<CableNo|pad:2>>", "Cable Type": "Power", "Repeat": "Per power cable"}],
        "equipment_list": [{"Tag": "<<Tag>>", "Description": "<<LoadType.Name|upper>>"}, {"Tag": "<<Tag>>-M"}]}


def test_round_trip_one_sheet_per_list_and_a_tags_sheet() -> None:
    sheets = export_type_rows(ROWS, None, [("<<Tag>>", "the tag")], [("<<LoadType.Name>>", "the load type's name")],
                              [("<<Tag|upper>>", "UPPER CASE")])
    assert [t for t, _ in sheets] == ["Cable Schedule", "Equipment List", "Instrument List", "PLC I-O List", "Tags"]
    cable = dict(sheets)["Cable Schedule"]
    assert cable[0] == [*LISTS["cable_schedule"].columns, "Repeat"] and cable[1][0] == "<<Tag>>-P<<CableNo|pad:2>>"
    assert dict(sheets)["Instrument List"] == [list(LISTS["instrument_list"].columns)]  # every list, even with no rows
    assert dict(sheets)["Tags"][1:] == [["<<Tag>>", "the tag", "the row's tag"], ["<<LoadType.Name>>", "the load type's name",
                                                                                    "linked record (dot notation)"],
                                       ["<<Tag|upper>>", "UPPER CASE", "modifier"]]
    back = import_type_rows(read_sheets(write_sheets(sheets)))
    assert back.payload == {"cable_schedule": ROWS["cable_schedule"], "equipment_list": ROWS["equipment_list"],
                            "instrument_list": [], "plc_io_list": []}
    assert back.notes == []


def test_project_columns_missing_sheets_and_unknown_headings() -> None:
    cols = {"equipment_list": ["Tag", "Notes"]}
    sheets = dict(export_type_rows({"equipment_list": [{"Tag": "T", "Notes": "n"}]}, cols))
    assert sheets["Equipment List"] == [["Tag", "Notes"], ["T", "n"]]
    # headings ignore case and spaces; a list with no sheet stays as it is
    parsed = import_type_rows({"equipment list": [{"TAG": "A", "no tes": "x"}]}, cols)
    assert parsed.payload == {"equipment_list": [{"Tag": "A", "Notes": "x"}]}
    assert 'No "Cable Schedule" sheet: those rows stay as they are.' in parsed.notes
    with pytest.raises(ValueError, match="Equipment List: not a column of the Equipment List: remarks"):
        import_type_rows({"equipment list": [{"tag": "A", "remarks": "x"}]}, cols)
