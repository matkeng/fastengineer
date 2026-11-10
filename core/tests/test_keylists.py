# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
from __future__ import annotations

import pytest
from pydantic import ValidationError

from workbench_core.keylists import (
    AREA_TYPES,
    PACKAGE_TYPES,
    PHASES,
    RATING_UNITS,
    EquipmentPackage,
    EquipmentPackageList,
    EquipmentType,
    PlantArea,
    PlantAreaList,
    check_equipment_packages,
    check_load_types,
    check_plant_areas,
    plant_area_depth,
)
from workbench_core.refdata import RefValidationError


def _areas(*nodes: tuple) -> PlantAreaList:
    """(id, parent, wbs, tag, description, type)"""
    return PlantAreaList(nodes=[PlantArea(id=i, parent_id=p, wbs=w, tag=t, description=d, area_type=k)
                                for i, p, w, t, d, k in nodes])


def test_area_types() -> None:
    assert AREA_TYPES == ["WBS", "Area", "Building", "Room", "Panel"]
    with pytest.raises(ValidationError):
        PlantArea(tag="A", description="A", area_type="Shed")


def test_valid_list_is_trimmed_and_ordered_parents_first() -> None:
    out = check_plant_areas(_areas(
        ("r", "b", "", "R-101", "Control room", "Room"),
        ("b", "a", " 1.1 ", " B-10 ", " Substation ", "Building"),
        ("a", None, "1", "A-100", "Process area", "Area"),
        ("p", "r", "", "LCP-01", "Local control panel", "Panel"),
        ("w", None, "2", "W-2", "Utilities", "WBS"),
        # Any type may sit under any other.
        ("x", "p", "", "A-900", "Area inside a panel", "Area"),
    ))
    assert [n.id for n in out.nodes] == ["a", "b", "r", "p", "x", "w"]
    b = out.nodes[1]
    assert (b.wbs, b.tag, b.description) == ("1.1", "B-10", "Substation")
    assert plant_area_depth(out) == 5
    assert plant_area_depth(PlantAreaList()) == 0


def test_tag_and_description_are_required_and_unique_in_the_whole_list() -> None:
    with pytest.raises(RefValidationError) as e:
        check_plant_areas(_areas(
            ("a", None, "", "A-100", "Process area", "Area"),
            ("b", "a", "", "a-100", "Pump house", "Building"),        # same tag, other case
            ("c", None, "", "A-200", "pump  HOUSE", "Area"),          # same description, another level
            ("d", None, "", " ", "", "WBS"),
        ))
    assert e.value.fields == {
        "b.tag": "Tag number 'a-100' is used twice",
        "c.description": "Description 'pump  HOUSE' is used twice",
        "d.tag": "Tag number is required",
        "d.description": "Description is required",
    }


def test_wbs_is_optional_but_unique_when_filled() -> None:
    ok = check_plant_areas(_areas(("a", None, "", "A", "One", "Area"), ("b", None, "", "B", "Two", "Area")))
    assert len(ok.nodes) == 2
    with pytest.raises(RefValidationError) as e:
        check_plant_areas(_areas(("a", None, "1.2", "A", "One", "Area"), ("b", "a", " 1.2", "B", "Two", "Room")))
    assert e.value.fields == {"b.wbs": "WBS number '1.2' is used twice"}


def test_parents_must_exist_and_not_loop() -> None:
    with pytest.raises(RefValidationError) as e:
        check_plant_areas(_areas(("a", "zz", "", "A", "One", "Area")))
    assert e.value.fields == {"a.parent": "Its parent is not in the list"}
    with pytest.raises(RefValidationError) as e:
        check_plant_areas(_areas(("a", "b", "", "A", "One", "Area"), ("b", "a", "", "B", "Two", "Area")))
    assert set(e.value.fields) == {"a.parent", "b.parent"}
    with pytest.raises(RefValidationError):
        check_plant_areas(_areas(("a", None, "", "A", "One", "Area"), ("a", None, "", "B", "Two", "Area")))


# -- equipment packages ---------------------------------------------------------

def _packages(*items: tuple) -> EquipmentPackageList:
    """(id, number, description, vendor, type)"""
    return EquipmentPackageList(items=[EquipmentPackage(id=i, number=n, description=d, vendor=v, package_type=t)
                                       for i, n, d, v, t in items])


def test_package_types() -> None:
    assert PACKAGE_TYPES == ["Vendor", "Client", "SWR Supplier", "Valves", "Instrumentation", "Large Mech",
                             "Installer", "Other"]
    with pytest.raises(ValidationError):
        EquipmentPackage(number="P-1", description="Pumps", package_type="Electrical")


def test_packages_are_trimmed_and_keep_their_order() -> None:
    out = check_equipment_packages(_packages(
        ("b", " PKG-020 ", " Control valves ", " Acme ", "Valves"),
        ("a", "PKG-010", "Feed pumps", "Acme", "Large Mech"),      # the same vendor again is fine
        ("c", "PKG-030", "Site installation", "", "Installer"),   # and so is no vendor
    ))
    assert [i.id for i in out.items] == ["b", "a", "c"]
    assert (out.items[0].number, out.items[0].description, out.items[0].vendor) == ("PKG-020", "Control valves", "Acme")


def test_package_number_and_description_are_required_and_unique() -> None:
    with pytest.raises(RefValidationError) as e:
        check_equipment_packages(_packages(
            ("a", "PKG-010", "Feed pumps", "", "Vendor"),
            ("b", "pkg-010", "Control valves", "", "Valves"),
            ("c", "PKG-030", "feed  PUMPS", "", "Other"),
            ("d", " ", "", "Acme", "Client"),
        ))
    assert e.value.fields == {
        "b.number": "Package number 'pkg-010' is used twice",
        "c.description": "Description 'feed  PUMPS' is used twice",
        "d.number": "Package number is required",
        "d.description": "Description is required",
    }
    with pytest.raises(RefValidationError):
        check_equipment_packages(_packages(("a", "P-1", "One", "", "Other"), ("a", "P-2", "Two", "", "Other")))


# -- equipment types (under a package) ----------------------------------------------

_PKGS = (("a", "PKG-010", "Feed pumps", "", "Large Mech"), ("b", "PKG-020", "Control valves", "", "Valves"))


def _with_types(*types: tuple, packages: tuple = _PKGS) -> EquipmentPackageList:
    """(id, package, name, description)"""
    return _packages(*packages).model_copy(update={"types": [
        EquipmentType(id=i, package_id=p, name=n, description=d) for i, p, n, d in types]})


def test_types_are_trimmed_and_grouped_by_package_in_order() -> None:
    out = check_equipment_packages(_with_types(
        ("t3", "b", " Globe valve ", " Throttling "), ("t1", "a", "Centrifugal pump", ""),
        ("t4", "b", "Ball valve", ""), ("t2", "a", "Dosing pump", ""),
    ))
    assert [(t.id, t.package_id) for t in out.types] == [("t1", "a"), ("t2", "a"), ("t3", "b"), ("t4", "b")]
    assert (out.types[2].name, out.types[2].description) == ("Globe valve", "Throttling")
    # A list saved before there were types is still valid.
    assert EquipmentPackageList.model_validate({"items": []}).types == []


def test_type_name_is_required_and_unique_across_packages() -> None:
    with pytest.raises(RefValidationError) as e:
        check_equipment_packages(_with_types(
            ("t1", "a", "Pump", ""), ("t2", "a", "pump", ""),     # same package
            ("t3", "b", " PUMP ", ""),                            # another package
            ("t4", "b", " ", "no name"),
        ))
    assert e.value.fields == {"t2.name": "Name 'pump' is used twice", "t3.name": "Name 'PUMP' is used twice",
                              "t4.name": "Name is required"}
    with pytest.raises(RefValidationError):
        check_equipment_packages(_with_types(("t1", "a", "Pump", ""), ("t1", "b", "Valve", "")))


def test_a_type_needs_a_package_of_the_list() -> None:
    with pytest.raises(RefValidationError) as e:
        check_equipment_packages(_with_types(("t1", "zz", "Pump", ""), ("t2", "", "Valve", "")))
    assert e.value.fields == {"t1.package": "Its package is not in the list", "t2.package": "Its package is not in the list"}
    # So a package can't be removed while it still has types.
    with pytest.raises(RefValidationError) as e:
        check_equipment_packages(_with_types(("t1", "a", "Pump", ""), ("t2", "b", "Valve", ""), packages=_PKGS[:1]))
    assert e.value.fields == {"t2.package": "Its package is not in the list"}


# -- load types ---------------------------------------------------------------------

def _load(**fields) -> dict:
    return {"id": "a", "code": "DOL", "name": "Direct on line", "rating_unit": "kW", "voltage": 415,
            "phases": "AC-3-phase"} | fields


def test_load_type_choices() -> None:
    assert RATING_UNITS == ["kW", "Amps"]
    assert PHASES == ["AC-3-phase", "AC-3-phase+N", "AC-1-phase-LN", "AC-1-phase-LL", "DC", "DC-mA"]


def test_load_types_are_converted_and_keep_their_order() -> None:
    out = check_load_types([
        _load(id="b", code=" VSD ", name=" Variable speed drive ", voltage="690", from_value="2.50", to_value=75,
              std_drg=" E-STD-012 ", bucket_type="B2", load_type="Motor", field_options="LCS", multi_load="yes",
              load_qty="2"),
        _load(),
    ])
    assert [r.id for r in out.items] == ["b", "a"]
    b, a = out.items
    assert (b.code, b.name, b.voltage, b.from_value, b.to_value, b.std_drg) == (
        "VSD", "Variable speed drive", 690, "2.5", "75", "E-STD-012")
    assert (b.multi_load, b.load_qty) == (True, 2)
    # Only code, name, kW/Amps, voltage and phases are needed.
    assert (a.from_value, a.to_value, a.std_drg, a.multi_load, a.load_qty) == (None, None, "", False, None)
    # A range may be one-sided, or a single value.
    assert check_load_types([_load(from_value="5", to_value=""), _load(id="b", code="X", name="Y", from_value=5, to_value="5.0")])


def test_load_type_required_fields_and_uniqueness() -> None:
    with pytest.raises(RefValidationError) as e:
        check_load_types([
            _load(),
            _load(id="b", code="dol", name="DIRECT  on line"),
            {"id": "c", "code": " ", "name": "", "voltage": ""},
        ])
    assert e.value.fields == {
        "b.code": "Code 'dol' is used twice", "b.name": "Name 'DIRECT  on line' is used twice",
        "c.code": "Code is required", "c.name": "Name is required", "c.rating_unit": "Choose kW or Amps",
        "c.phases": "Choose the phases", "c.voltage": "Voltage is required",
    }
    with pytest.raises(RefValidationError):
        check_load_types([_load(), _load(code="X", name="Y")])  # the same id


def test_load_type_numbers() -> None:
    with pytest.raises(RefValidationError) as e:
        check_load_types([_load(voltage="415V", from_value="ten", to_value="1e", load_qty="1.5", rating_unit="HP",
                                phases="AC", multi_load="maybe")])
    assert e.value.fields == {
        "a.voltage": "Not a whole number", "a.from_value": "Not a number", "a.to_value": "Not a number",
        "a.load_qty": "Not a whole number", "a.rating_unit": "Choose kW or Amps", "a.phases": "Choose the phases",
        "a.multi_load": "Not yes/no",
    }
    with pytest.raises(RefValidationError) as e:
        check_load_types([_load(voltage=-24, load_qty=-1, from_value="10", to_value="9.99")])
    assert e.value.fields == {"a.voltage": "Can't be negative", "a.load_qty": "Can't be negative",
                              "a.to_value": "Must not be less than the From value"}


# -- load list: automatic fill ---------------------------------------------------------

def test_auto_match_is_exact_and_unambiguous() -> None:
    from workbench_core.keylists import LoadListRow, apply_auto, auto_match, match_index

    index = match_index([("a", "100"), ("b", " Area  2 "), ("c", "dup"), ("d", "DUP"), ("e", "")])
    assert auto_match("100", index) == "a" and auto_match("area 2", index) == "b"
    assert auto_match("dup", index) is None  # two items share the text
    assert auto_match("10", index) is None and auto_match(None, index) is None and auto_match(True, index) is None
    assert auto_match(100, index) == "a"  # a number read from the file

    row = LoadListRow(recipe_id="r", key="P-1", source="MEL", target="MEL", values={"area": "100", "load_type": "x"})
    row = apply_auto(row, index, {})
    assert (row.plant_area_id, row.plant_area_by, row.load_type_id, row.load_type_by) == ("a", "auto", None, None)
    # Automatic allocations follow the text; a person's choice (even "none") is kept.
    moved = apply_auto(row.model_copy(update={"values": {"area": "area 2"}}), index, {})
    assert (moved.plant_area_id, moved.plant_area_by) == ("b", "auto")
    mine = row.model_copy(update={"plant_area_id": None, "plant_area_by": "user"})
    assert apply_auto(mine, index, {}).plant_area_id is None


def test_panels_and_supply() -> None:
    from workbench_core.keylists import LoadListRow, apply_auto, apply_auto_supply, panel_index, supply_loop

    def row(key: str, **values) -> LoadListRow:
        return LoadListRow(recipe_id="r", key=key, source="EEL", target="EEL", values={"tag": key} | values)

    mcc = apply_auto(row("MCC-1", is_a_loadcentre=True), {}, {})
    assert (mcc.is_panel, mcc.is_panel_by) == (True, "auto")
    pump = apply_auto(row("P-1", is_a_loadcentre=False, supplied_from="mcc-1"), {}, {})
    assert (pump.is_panel, pump.is_panel_by) == (False, "auto")
    assert apply_auto(row("X"), {}, {}).is_panel_by is None  # not mapped: nothing filled in
    panels = panel_index([mcc, pump])
    assert apply_auto_supply(pump, panels).supplied_from == "r/MCC-1"
    assert apply_auto_supply(mcc.model_copy(update={"values": {"supplied_from": "MCC-1"}}), panels).supplied_from is None  # not itself
    mine = pump.model_copy(update={"supplied_from": "primary", "supplied_from_by": "user"})
    assert apply_auto_supply(mine, panels).supplied_from == "primary"

    a = row("A").model_copy(update={"supplied_from": "r/B"})
    b = row("B").model_copy(update={"supplied_from": "r/C"})
    c = row("C").model_copy(update={"supplied_from": "r/A"})
    d = row("D").model_copy(update={"supplied_from": "r/A"})
    assert supply_loop({r.ref(): r for r in (a, b, c, d)}) == ["r/A", "r/B", "r/C"]
    assert supply_loop({r.ref(): r for r in (a, b, d)}) == []
