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
    assert [row.cells for row in ll.rows][1] == ["P-2", "P-2 pump", 100, "DOL", 7.5, "kW", 415, "AC-3-phase", "MCC-1", ""]
    assert ll.rows[0].cells[-1] == "Yes"


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
