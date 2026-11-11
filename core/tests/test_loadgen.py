# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
from workbench_core.keylists import LoadListRow, LoadType
from workbench_core.keylists.loadgen import LISTS, TEMPLATE_LISTS, generate, missing_load_types
from workbench_core.keylists.validate import check_load_types

AREAS = {"a1": ("100", "Feed area")}


def _type(**rows) -> LoadType:
    return LoadType(id="t1", code="DOL", name="Direct on line", rating_unit="kW", voltage=415, phases="AC-3-phase",
                    std_drg="E-STD-01", rows=rows)


def _load(key: str, **more) -> LoadListRow:
    base = dict(recipe_id="m", key=key, source="Plant MEL", target="MEL", values={"tag": key, "desc": f"{key} pump",
                "load_rating": 7.5, "area": "100"}, plant_area_id="a1", load_type_id="t1", supplied_from="m/MCC-1")
    return LoadListRow(**(base | more))


MCC = LoadListRow(recipe_id="m", key="MCC-1", source="Plant MEL", target="MEL", values={"tag": "MCC-1", "desc": "MCC"},
                  is_panel=True, supplied_from="primary", load_type_id="t1")


def test_lists() -> None:
    assert TEMPLATE_LISTS == ["cable_schedule", "equipment_list", "instrument_list", "plc_io_list"]
    assert [x.deliverable_type for x in LISTS.values()] == ["Cable Schedule", "Equipment List", "Instrument List",
                                                           "PLC I/O List", "Load List"]
    assert all(x.diff_key in x.columns for x in LISTS.values())


def test_rows_and_tags() -> None:
    lt = _type(cable_schedule=[
        {"Cable Number": "<<Tag>>-P<<ROW>>", "From": "<<SuppliedFrom>>", "From Description": "<<suppliedfromdesc>>",
         "To": "<< tag >>", "To Description": "<<Description>>", "Voltage": "<<Voltage>>", "Size": "2.5",
         "Remarks": "<<LoadType>> <<StdDrg>> <<Rating>> <<Units>> in <<PlantArea>> (<<PlantAreaDesc>>) <<Nope>>"},
        {"Cable Number": "<<Tag>>-C<<Row>>", "Remarks": "<<load_rating>>/<<Phases>>"}])
    loads = [_load("P-10"), _load("P-2"), MCC, _load("P-9", status="deleted")]
    r = generate("cable_schedule", loads, {"t1": lt}, AREAS)
    assert r.header == list(LISTS["cable_schedule"].columns)
    numbers = [row.cells[0] for row in r.rows]
    assert numbers == ["MCC-1-P1", "MCC-1-C2", "P-2-P1", "P-2-C2", "P-10-P1", "P-10-C2"]  # active loads, tags in number order
    p2 = dict(zip(r.header, r.rows[2].cells))
    assert (p2["From"], p2["From Description"], p2["To"], p2["To Description"], p2["Voltage"], p2["Size"]) == (
        "MCC-1", "MCC", "P-2", "P-2 pump", 415, 2.5)
    assert p2["Remarks"] == "DOL E-STD-01 7.5 kW in 100 (Feed area) <<Nope>>"
    assert r.rows[3].cells[-1] == "7.5/AC-3-phase" and r.rows[0].cells[1] == "Primary Supply"
    assert (r.unresolved_tokens, r.unresolved_count) == (["<<Nope>>"], 3)
    assert (r.rows[2].run_row_id, r.rows[2].template_id, r.rows[3].template_seq) == ("m/P-2", "DOL", 2)
    # A list the load type has no rows for is empty; the Load List has one row per load.
    assert generate("plc_io_list", loads, {"t1": lt}, AREAS).rows == []
    ll = generate("load_list", loads, {"t1": lt}, AREAS)
    assert [row.cells for row in ll.rows][1][:10] == ["P-2", "P-2 pump", 100, "DOL", 7.5, "kW", 415, "AC-3-phase", "MCC-1", ""]
    assert ll.rows[0].cells[9] == "Yes"
    # then the cable columns and the Load List's fields, by their names (one used already gets " (import)")
    assert ll.header[10:12] == ["Cable Length (m)", "Power Cable"] and {"Area", "Load rating", "Voltage (import)"} <= set(ll.header)
    p2 = dict(zip(ll.header, ll.rows[1].cells))
    assert p2["Load rating"] == 7.5 and p2["Cable Length (m)"] == ""


def test_missing_load_types() -> None:
    loads = [_load("P-1"), _load("P-2", load_type_id=None), _load("P-3", load_type_id="gone"),
             _load("P-4", load_type_id=None, status="deleted")]
    assert missing_load_types(loads, {"t1": _type()}) == ["P-2", "P-3"]


def test_load_type_rows_are_checked() -> None:
    import pytest

    from workbench_core.refdata import RefValidationError
    base = {"id": "t1", "code": "DOL", "name": "DOL", "rating_unit": "kW", "voltage": 415, "phases": "AC-3-phase"}
    out = check_load_types([base | {"rows": {"cable_schedule": [{"Cable Number": " <<Tag>>-P1 ", "Size": 2.5, "Route": " "}, {}],
                                             "plc_io_list": []}}])
    assert out.items[0].rows == {"cable_schedule": [{"Cable Number": "<<Tag>>-P1", "Size": "2.5"}]}
    assert check_load_types([base]).items[0].rows == {}
    with pytest.raises(RefValidationError) as e:
        check_load_types([base | {"rows": {"cable_schedule": [{"Colour": "red"}], "drawings": []}}])
    assert set(e.value.fields) == {"t1.rows.cable_schedule", "t1.rows"}


# -- cables: matched from the Cable Types list, and rows that repeat per cable -----------------

from workbench_core.keylists.cable_types import default_cable_types, guess_insulation  # noqa: E402
from workbench_core.keylists.loadgen import PER_CABLE, REPEAT, match_cable  # noqa: E402

CABLES = default_cable_types()
POWER = {REPEAT: PER_CABLE, "Cable Number": "<<Tag>>-P<<CableNo>>", "To": "<<Tag>>", "Cable Type": "Power", "Cores": "3C+E",
         "Size": "<<CableSize>>", "Length (m)": "<<CableLength>>", "Remarks": "<<Phase>>|<<CableDesc>>|<<CableParallel>>"}


def _cables(load: LoadListRow, *rows: dict, phases: str = "AC-3-phase") -> tuple[list[dict], list[str]]:
    lt = _type(cable_schedule=list(rows or (POWER,))).model_copy(update={"phases": phases})
    notes: list[str] = []
    r = generate("cable_schedule", [load], {"t1": lt}, AREAS, CABLES, notes)
    assert r.unresolved_count == 0, r.unresolved_tokens
    return [dict(zip(r.header, row.cells)) for row in r.rows], notes


def test_insulation_of_the_default_cable_types() -> None:
    assert guess_insulation("Cu-XLPE-PVC-X90 (Power)") == "XLPE" and guess_insulation("Cu-PVC-PVC-V90 (Power)") == "PVC"
    assert guess_insulation("Flex-Cu-XLPE-TPE-90C (Flex Power)") == "XLPE" and guess_insulation("Cu-Bare-Earth") == ""
    assert guess_insulation("Cu-V90RPPVC-OvScn-V90RPPVC (Instrolex Pairs)") == "PVC"
    assert {c.insulation for c in CABLES if c.type == "Power"} == {"PVC", "XLPE"}


def test_match_cable() -> None:
    c, why = match_cable(CABLES, "Power", "3C+E", "70", "XLPE")
    assert c and c.code == "AC_415V - Power - 3C+E - 70" and why == ""
    assert match_cable(CABLES, "power", " 3c+e ", "2.50", "pvc")[0].code == "AC_415V - Power - 3C+E - 2.5"
    none, why = match_cable(CABLES, "Power", "3C+E", "70", "PVC")
    assert none is None and why == "no cable type is Power 3C+E 70 mm² PVC"
    # 2C+E 2.5 flex exists only for 240 V; 1C flex 500 once; insulation left blank is not compared
    assert match_cable(CABLES, "Power", "3C+E", "70")[0].insulation == "XLPE"
    two = [x.model_copy(update={"id": "x", "code": "Other", "application": "AC_690V"}) for x in CABLES if x.code == "AC_415V - Power - 3C+E - 70"]
    assert match_cable(CABLES + two, "Power", "3C+E", "70", "XLPE")[0] is None  # two match, nothing to choose by
    assert match_cable(CABLES + two, "Power", "3C+E", "70", "XLPE", "415")[0].code == "AC_415V - Power - 3C+E - 70"


def test_one_row_per_parallel_multicore_cable() -> None:
    rows, notes = _cables(_load("P-1", cable_size="70", cable_insulation="XLPE", cable_length=120))
    assert notes == [] and len(rows) == 1
    assert (rows[0]["Cable Number"], rows[0]["Cable Type"], rows[0]["Cable Code"], rows[0]["Cores"], rows[0]["Size"],
            rows[0]["Length (m)"], rows[0]["Remarks"]) == ("P-1-P1", "Power", "AC_415V - Power - 3C+E - 70", "3C+E", 70, 120,
                                                           "|Cu-XLPE-PVC-X90 (Power)|1")
    rows, notes = _cables(_load("P-1", cable_size="50", cable_insulation="XLPE", cable_parallel=2))
    assert notes == [] and [(r["Cable Number"], r["Size"], r["Cable Code"]) for r in rows] == [
        ("P-1-P1", 50, "AC_415V - Power - 3C+E - 50"), ("P-1-P2", 50, "AC_415V - Power - 3C+E - 50")]


def test_single_core_sets_and_their_earth() -> None:
    load = _load("P-1", cable_size="300", cable_insulation="XLPE", cable_construction="Single core", earth_size="120")
    rows, notes = _cables(load)
    assert notes == []
    assert [(r["Cable Number"], r["Remarks"].split("|")[0], r["Cores"], r["Size"], r["Cable Code"]) for r in rows] == [
        ("P-1-P1", "L1", "1C", 300, "AC_415V - Power - 1C - 300"), ("P-1-P2", "L2", "1C", 300, "AC_415V - Power - 1C - 300"),
        ("P-1-P3", "L3", "1C", 300, "AC_415V - Power - 1C - 300"), ("P-1-P4", "E", "1C", 120, "Earth - PVC - 1C - 120")]
    rows, _ = _cables(load.model_copy(update={"cable_parallel": 2}))
    assert [r["Remarks"].split("|")[0] for r in rows] == ["L1", "L2", "L3", "L1", "L2", "L3", "E"]
    rows, _ = _cables(load, phases="AC-3-phase+N")
    assert [r["Remarks"].split("|")[0] for r in rows] == ["L1", "L2", "L3", "N", "E"]
    rows, notes = _cables(load.model_copy(update={"earth_size": ""}))
    assert len(rows) == 4 and rows[3]["Cable Code"] == "" and notes == ["No cable for 1 load(s) (its earth cable size is not set): P-1"]


def test_several_repeating_rows_plain_rows_and_no_match() -> None:
    motor = POWER | {"Cable Number": "<<Tag>>-M<<CableNo>>", "Cable Type": "VSD", "Cores": "3C+3E"}
    control = {"Cable Number": "<<Tag>>-C1", "Cable Type": "Control", "Cores": "5+E", "Size": "1.5"}
    plain = {"Cable Number": "<<Tag>>-X", "Cable Type": "Power", "Cores": "4C+E", "Cable Code": "<<CableCode>>"}
    rows, notes = _cables(_load("P-1", cable_size="50", cable_insulation="XLPE", cable_parallel=2), POWER, motor, control, plain)
    assert notes == []
    assert [(r["Cable Number"], r["Cable Code"]) for r in rows] == [
        ("P-1-P1", "AC_415V - Power - 3C+E - 50"), ("P-1-P2", "AC_415V - Power - 3C+E - 50"),
        ("P-1-M1", "AC_415V - VSD - 3C+3E - 50"), ("P-1-M2", "AC_415V - VSD - 3C+3E - 50"),
        ("P-1-C1", ""), ("P-1-X", "AC_415V - Power - 4C+E - 50")]  # a plain row: one cable, whatever is in parallel
    assert (rows[4]["Cable Type"], rows[4]["Cores"], rows[4]["Size"]) == ("Control", "5+E", 1.5)

    # nothing typed in yet, or nothing in the table: the row is still there, the cable blank, and it is reported
    rows, notes = _cables(_load("P-1"), POWER, control)
    assert [(r["Cable Number"], r["Cable Code"], r["Size"]) for r in rows] == [("P-1-P1", "", ""), ("P-1-C1", "", 1.5)]
    assert notes == ["No cable for 1 load(s) (its cable size is not set): P-1"]
    rows, notes = _cables(_load("P-1", cable_size="70", cable_insulation="PVC"))
    assert rows[0]["Cable Code"] == "" and rows[0]["Size"] == 70 and "no cable type is Power 3C+E 70 mm² PVC" in notes[0]


def test_repeat_is_a_cable_schedule_setting_only() -> None:
    def check(rows: dict):
        return check_load_types([{"id": "t1", "code": "DOL", "name": "DOL", "rating_unit": "kW", "voltage": 415,
                                  "phases": "AC-3-phase", "rows": rows}]).items[0].rows
    assert check({"cable_schedule": [{"Repeat": "per power cable", "Cable Number": "x"}, {"Repeat": PER_CABLE}]}) == {
        "cable_schedule": [{"Repeat": PER_CABLE, "Cable Number": "x"}]}  # a row with only the setting is blank
    for bad in ({"cable_schedule": [{"Repeat": "Twice", "Cable Number": "x"}]}, {"equipment_list": [{"Repeat": PER_CABLE, "Tag": "x"}]}):
        try:
            check(bad)
        except Exception as exc:  # RefValidationError
            assert "rows" in str(getattr(exc, "fields", ""))
        else:
            raise AssertionError("accepted")
