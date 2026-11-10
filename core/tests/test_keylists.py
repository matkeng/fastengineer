# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
from __future__ import annotations

import pytest
from pydantic import ValidationError

from workbench_core.keylists import (
    AREA_TYPES,
    PACKAGE_TYPES,
    EquipmentPackage,
    EquipmentPackageList,
    PlantArea,
    PlantAreaList,
    check_equipment_packages,
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
