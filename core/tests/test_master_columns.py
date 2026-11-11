# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Editing the columns of the Project Master lists (keylists.master_columns)."""

from __future__ import annotations

import pytest

from workbench_core.keylists.instrument_runsheet import InstrumentRunsheet
from workbench_core.keylists.loadgen import LISTS, generate
from workbench_core.keylists.master import master_list
from workbench_core.keylists.master_columns import ColumnEdit, default_master_columns, plan_change, rename_in, rewrite_rows
from workbench_core.keylists.validate import check_load_types
from workbench_core.refdata import RefValidationError


def _edits(key: str, rename=None, drop=(), add=()) -> list[ColumnEdit]:
    rename = rename or {}
    return ([ColumnEdit(name=rename.get(c, c), was=c) for c in LISTS[key].columns if c not in drop]
            + [ColumnEdit(name=a) for a in add])


def test_plan_change_finds_renames_deletes_and_new_columns() -> None:
    ch = plan_change(default_master_columns(), {"instrument_list": _edits("instrument_list", {"Remarks": "Notes"}, ("Range",), ("Loop",))})
    one = ch["instrument_list"]
    assert one.renames == {"Remarks": "Notes"} and one.deletes == ["Range"] and one.added == ["Loop"]
    assert one.columns[-2:] == ["Notes", "Loop"] and "Range" not in one.columns
    # names are tidied: extra spaces go
    assert plan_change(default_master_columns(), {"plc_io_list": _edits("plc_io_list", add=("  Card   type ",))})["plc_io_list"].added == ["Card type"]


@pytest.mark.parametrize("edits, message", [
    (_edits("equipment_list", add=("TAG",)), "twice"),
    (_edits("equipment_list", add=("generator",)), "kept for"),
    (_edits("equipment_list", add=("",)), "needs a name"),
    (_edits("equipment_list", {"Tag": "Equipment Tag"}), "can be moved but not renamed"),
    (_edits("equipment_list", drop=("Tag",)), "can be moved but not renamed"),
    (_edits("equipment_list", drop=("Model",), add=("Model",)), "rename it instead"),
    ([ColumnEdit(name="Tag", was="Nope")], "is not a column"),
    ([ColumnEdit(name="Tag", was="Tag"), ColumnEdit(name="Tag 2", was="Tag")], "edited twice"),
])
def test_what_is_refused(edits, message) -> None:
    with pytest.raises(RefValidationError) as exc:
        plan_change(default_master_columns(), {"equipment_list": edits})
    assert message in " ".join(exc.value.fields.values())


def test_the_cable_columns_per_power_cable_rows_fill_in_are_protected() -> None:
    for c in ("Cable Type", "Cores", "Cable Code", "Cable Number"):
        with pytest.raises(RefValidationError):
            plan_change(default_master_columns(), {"cable_schedule": _edits("cable_schedule", drop=(c,))})
    moved = [*_edits("cable_schedule")]
    moved.insert(0, moved.pop(7))  # moving one is fine
    assert plan_change(default_master_columns(), {"cable_schedule": moved})["cable_schedule"].columns[0] == "Cores"


def test_rewrite_rows_and_deliverable_columns() -> None:
    ch = plan_change(default_master_columns(), {"cable_schedule": _edits("cable_schedule", {"Remarks": "Notes"}, ("Route",))})
    rows = {"cable_schedule": [{"Cable Number": "C1", "Route": "Tray", "Remarks": "x"}, {"Route": "only", "Repeat": "Per power cable"}],
            "equipment_list": [{"Tag": "T"}]}
    out, dropped = rewrite_rows(rows, ch)
    assert out == {"cable_schedule": [{"Cable Number": "C1", "Notes": "x"}], "equipment_list": [{"Tag": "T"}]} and dropped == 2
    assert rename_in(["remarks", "Route", "From"], ch["cable_schedule"]) == ["Notes", "From"]


def test_the_generators_follow_custom_columns() -> None:
    cols = ["Tag", "Weight", "Description"]
    types = check_load_types([{"code": "DOL", "name": "Motor", "rating_unit": "kW", "voltage": "415", "phases": "AC-3-phase",
                               "rows": {"equipment_list": [{"Tag": "<<Tag>>", "Weight": "12 kg"}]}}], {"equipment_list": cols})
    with pytest.raises(RefValidationError):  # the built-in columns don't have Weight
        check_load_types([{"code": "DOL", "name": "Motor", "rating_unit": "kW", "voltage": "415", "phases": "AC-3-phase",
                           "rows": {"equipment_list": [{"Weight": "12 kg"}]}}])
    power = generate("equipment_list", [], {t.id: t for t in types.items}, {}, columns=cols)
    assert power.header == cols
    master = master_list("equipment_list", power, InstrumentRunsheet(), {}, {}, cols)
    assert master.header == [*cols, "Generator", "Confirmed"]
