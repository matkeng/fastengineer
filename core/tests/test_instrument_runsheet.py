# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
import pytest

from workbench_core.keylists.instrument_runsheet import (COLUMNS, HEADINGS, KEYS, TAGS, InstrumentRunsheet, TypedRow, as_typed,
                                                         check_runsheet, index, problems, row_label)
from workbench_core.refdata import RefValidationError

TYPES = index([("t1", "Startup Siren - Single"), ("t2", "PRIMARY CRUSHER")])
AREAS = index([("a1", "3510")])
PARENTS = {"3510-cr3001": "3510-CR3001", "3510-cv3002": "3510-CV3002"}


def _row(rid: str, *cells) -> TypedRow:
    return TypedRow(id=rid, cells=list(cells))


def test_columns_and_tags() -> None:
    assert len(COLUMNS) == 43 and HEADINGS[:8] == ["Equipment Type Ref", "Area Ref", "Parent Equipment Ref", "Name Suffix", "PID",
                                                 "IO via MARSHALLING BOX", "Confirmed", "PLC Rack Num"]
    assert (HEADINGS[8], HEADINGS[-1], KEYS[8], KEYS[-1]) == ("#1", "#35", "1", "35")
    assert [t for t, _ in TAGS][:9] == ["<<STD>>", "<<Area>>", "<<MECH>>", "<<SUF>>", "<<PID>>", "<<VIA_MB>>", "<<CONF>>", "<<Rack>>",
                                        "<<#1>>"] and TAGS[-1][0] == "<<#35>>"


def test_rows_are_resolved_and_kept_as_typed() -> None:
    rows = [_row("r1", " primary  crusher ", 3510, "3510-cr3001", "", "3510-P-PID-507", "", True, 1001, 10441, 10442.0, "0045"),
            _row("r2"), _row("r3", "", "", "", "", "", "", "FALSE"),  # blank rows go
            _row("r4", "Startup Siren - Single", "3510", "3510-CV3002", "A", "", "**CV**-CPL1", "no", "1001", "10334"),
            _row("r4", "Startup Siren - Single", "3510", "3510-CV3002", "", "", "", "", "", "10335")]  # may repeat; a new id
    sheet = check_runsheet(rows, TYPES, AREAS, PARENTS)
    assert [r.id for r in sheet.rows][:2] == ["r1", "r4"] and len({r.id for r in sheet.rows}) == 3
    first = sheet.rows[0]
    assert (first.equipment_type_id, first.plant_area_id, first.parent_tag, first.pid, first.confirmed, first.rack) == (
        "t2", "a1", "3510-CR3001", "3510-P-PID-507", True, "1001")
    assert first.numbers[:4] == ["10441", "10442", "0045", ""] and len(first.numbers) == 35
    assert (sheet.rows[1].via_mb, sheet.rows[1].suffix, sheet.rows[1].confirmed, sheet.rows[2].confirmed) == ("**CV**-CPL1", "A", False, False)

    typed = as_typed(sheet, {"t1": "Startup Siren - Single", "t2": "PRIMARY CRUSHER"}, {"a1": "3510"})
    assert typed[0].cells[:9] == ["PRIMARY CRUSHER", "3510", "3510-CR3001", "", "3510-P-PID-507", "", "TRUE", "1001", "10441"]
    assert len(typed[0].cells) == 43 and check_runsheet(typed, TYPES, AREAS, PARENTS).rows == sheet.rows  # round trip
    assert as_typed(sheet, {}, {})[0].cells[:2] == ["", ""]  # a type or area that is gone
    assert row_label(typed[0], 1) == "Row 1 (PRIMARY CRUSHER / 3510-CR3001)" and row_label(TypedRow(), 4) == "Row 4"


def test_the_three_references_must_match() -> None:
    rows = [_row("r1", "Nope", "9999", "X-1", "", "", "", "maybe"), _row("r2", "", "", "", "S")]
    out, errors = problems(rows, TYPES, AREAS, PARENTS)
    assert set(errors) == {"r1.equipment_type", "r1.area", "r1.parent", "r1.confirmed", "r2.equipment_type", "r2.area", "r2.parent"}
    assert "'Nope' is not an equipment type" in errors["r1.equipment_type"] and errors["r2.area"] == "Area Ref is required"
    assert "Electrical Equipment List or the MEL" in errors["r1.parent"] and len(out) == 2
    with pytest.raises(RefValidationError) as exc:
        check_runsheet(rows, TYPES, AREAS, PARENTS)
    assert exc.value.fields == errors
    assert check_runsheet([], TYPES, AREAS, PARENTS) == InstrumentRunsheet()
