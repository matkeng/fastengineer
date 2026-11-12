# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Dot notation and modifiers in the generators' <<tags>> (keylists.tag_paths)."""

from __future__ import annotations

import pytest

from workbench_core.keylists import EquipmentType
from workbench_core.keylists.cable_types import CableType
from workbench_core.keylists.instrument_runsheet import InstrumentRunsheet, RunsheetRow
from workbench_core.keylists.loadgen import LISTS, expand, generate
from workbench_core.keylists.loadlist import LoadListRow
from workbench_core.keylists.master import instrument_rows
from workbench_core.keylists.models import EelItem, EquipmentCode, EquipmentPackage, LoadType, PlantArea
from workbench_core.keylists.plc import PlcList, PlcRack, PlcSystem
from workbench_core.keylists.tag_paths import Links, apply, help_paths, parse, resolve

TYPES = [LoadType(id="t1", code="DOL", name="Direct on line", rating_unit="kW", voltage=415, phases="AC-3-phase", std_drg="E-STD-01",
                  rows={"equipment_list": [{"Tag": "<<Tag>>", "Description": "<<LoadType.Name|upper>>",
                                            "Plant Area": "<<PlantArea.Parent.Parent.Tag|default:none>> / <<PlantArea.Parent.Tag>>",
                                            "Supplied From": "<<SuppliedFrom.LoadType.Code>>", "Rating": "<<Rating|dec:2>>",
                                            "Model": "<<Eel.EquipmentCode.Name|default:->>", "Remarks": "<<Nope.X>> <<LoadType.Nope>>"}],
                        "cable_schedule": [{"Cable Number": "<<Tag>>-<<CableNo|pad:2>>", "Cable Type": "Power", "Cores": "3C+E",
                                            "Remarks": "<<Cable.Insulation|lower>>"}]})]
AREAS = [PlantArea(id="w", tag="W-1", description="Plant", area_type="WBS"),
         PlantArea(id="a", parent_id="w", tag="100", description="Feed", area_type="Area"),
         PlantArea(id="b", parent_id="a", tag="B-1", description="Pump house", area_type="Building")]
CABLES = [CableType(code="C-16", application="AC_415V", type="Power", cores="3C+E", diameter="16", insulation="XLPE")]
CODES = [EquipmentCode(id="c1", code="MCC", name="Motor control centre")]
EEL = [EelItem(id="e1", tag="MCC-1", description="MCC", equipment_code_id="c1", plant_area_id="b")]


def _load(key: str, **more) -> LoadListRow:
    base = dict(recipe_id="m", key=key, source="MEL", target="MEL", values={"tag": key, "load_rating": 7.5}, plant_area_id="b",
                load_type_id="t1", supplied_from="eel/e1", cable_size="16", cable_insulation="XLPE")
    return LoadListRow(**(base | more))


MCC = LoadListRow(recipe_id="eel", key="e1", source="EEL", target="EEL", values={"tag": "MCC-1"}, load_type_id="t1",
                  plant_area_id="b", is_panel=True, supplied_from="primary")


def test_parse_and_modifiers() -> None:
    assert parse("LoadType.Name|upper|left:3") == (["LoadType", "Name"], [("upper", []), ("left", ["3"])])
    assert parse(r"Tag|replace:\::_") == (["Tag"], [("replace", [":", "_"])])
    cases = [("7.9", "int", "7"), ("7.46", "round:1", "7.5"), ("7", "round:2", "7"), ("7.5", "dec:2", "7.50"), ("7", "pad:3", "007"),
             ("-7.5", "pad:3", "-007.5"), ("P-101", "nohyphen", "P101"), (" a  b ", "trim", "a b"), ("feed pump", "title", "Feed Pump"),
             ("P-101", "left:3", "P-1"), ("P-101", "right:3", "101"), ("P-101", "replace:-:_", "P_101"), ("", "prefix:-", ""),
             ("A", "prefix:-", "-A"), ("7", "suffix: kW", "7 kW"), ("", "default:TBA", "TBA"), ("x", "default:TBA", "x"),
             ("abc", "int", "abc"), ("Pump", "upper|left:2", "PU")]
    for text, mods, want in cases:
        assert apply(text, parse(f"x|{mods}")[1]) == want, (text, mods)
    for bad, why in [("x|shout", "no modifier 'shout'"), ("x|left", "needs 1"), ("x|left:a", "whole number")]:
        with pytest.raises(ValueError, match=why):
            apply("x", parse(bad)[1])


def test_paths_through_a_loads_links() -> None:
    links = Links(load_types=TYPES, areas=AREAS, loads=[MCC, _load("P-1")], eel=EEL, codes=CODES, cables=CABLES)
    root = links.load(_load("P-1"))
    get = lambda t: resolve(t, {}, root)[0]  # noqa: E731
    assert get("LoadType.Name") == "Direct on line" and get("loadtype.std_drg") == "E-STD-01" and get("LOADTYPE . STD DRG") == "E-STD-01"
    assert get("PlantArea.Parent.Tag") == "100" and get("PlantArea.Parent.Parent.Description") == "Plant"
    assert get("PlantArea.Parent.Parent.Parent.Tag") == ""  # no link there: blank
    assert get("SuppliedFrom") == "MCC-1" and get("SuppliedFrom.Eel.EquipmentCode.Name") == "Motor control centre"
    assert get("SuppliedFrom.SuppliedFrom") == "Primary Supply" and get("LoadType") == "DOL"
    assert resolve("Nope.X", {}, root)[2] == "'Nope' is not a link of a load (a Load List row) (its links: LoadType, PlantArea, SuppliedFrom, Eel, Cable, Motor, Drive, Starter)"
    assert "not a field of a load type" in resolve("LoadType.Nope", {}, root)[2]
    assert resolve("Rating|dec:2", {"rating": "7.5"}, root)[:2] == ("7.50", True)  # stays as written
    assert resolve("Nope", {}, root) == (None, False, None)  # a plain tag that matches nothing: as before


def test_the_power_generator_fills_dotted_tags() -> None:
    loads = [MCC, _load("P-1")]
    unresolved: dict[str, int] = {}
    eq = generate("equipment_list", loads, {t.id: t for t in TYPES}, {}, links=Links(
        load_types=TYPES, areas=AREAS, loads=loads, eel=EEL, codes=CODES, cables=CABLES))
    p1 = dict(zip(LISTS["equipment_list"].columns, eq.rows[1].cells))
    assert p1["Description"] == "DIRECT ON LINE" and p1["Plant Area"] == "W-1 / 100" and p1["Supplied From"] == "DOL"
    assert p1["Rating"] == "7.50" and p1["Model"] == "-"
    mcc = dict(zip(LISTS["equipment_list"].columns, eq.rows[0].cells))
    assert mcc["Model"] == "Motor control centre"
    assert sorted(eq.unresolved_tokens) == ["<<LoadType.Nope>> ('Nope' is not a field of a load type (its fields: Code, Name, RatingUnit, "
                                            "Voltage, Phases, From, To, StdDrg, BucketType, LoadType, FieldOptions, MultiLoad, LoadQty, StarterChart))",
                                            "<<Nope.X>> ('Nope' is not a link of a load (a Load List row) (its links: LoadType, PlantArea, "
                                            "SuppliedFrom, Eel, Cable, Motor, Drive, Starter))"]
    # a <<Cable.…>> tag makes it a cable row: the matched Cable Types row
    cs = generate("cable_schedule", [_load("P-1")], {t.id: t for t in TYPES}, {}, CABLES)
    row = dict(zip(LISTS["cable_schedule"].columns, cs.rows[0].cells))
    assert row["Cable Number"] == "P-1-01" and row["Remarks"] == "xlpe"
    assert expand("<<LoadType.Name>>", {}, unresolved) == "<<LoadType.Name>>" and unresolved  # without links: as before


def test_the_instrument_generator_follows_its_links() -> None:
    kind = EquipmentType(id="t1", package_id="p1", name="Siren", rows={"instrument_list": [
        {"Tag": "<<MECH>>-HA<<#1|int|pad:3>>", "Description": "<<EquipmentType.Package.Vendor|default:TBA>>",
         "Service": "<<Parent.LoadType.Code>> <<Parent.PlantArea.Parent.Tag>>", "Remarks": "<<Rack.System.Tag>>/<<Rack.Description>>"}]})
    sheet = InstrumentRunsheet(rows=[RunsheetRow(id="r1", equipment_type_id="t1", plant_area_id="b", parent_tag="p-1", rack="R1",
                                                 numbers=["7.0"])])
    plc = PlcList(systems=[PlcSystem(tag="PLC-1", racks=[PlcRack(tag="r1", rack_type_id="x", description="Main rack")])])
    links = Links(load_types=TYPES, areas=AREAS, loads=[_load("P-1")], packages=[EquipmentPackage(id="p1", number="PKG", description="d",
                                                                                                    package_type="Vendor")],
                  equipment_types=[kind], plc=plc)
    unresolved: dict[str, int] = {}
    row = dict(zip(LISTS["instrument_list"].columns, instrument_rows("instrument_list", sheet, {"t1": kind}, {}, unresolved, links=links)[0][0].cells))
    assert row["Tag"] == "p-1-HA007" and row["Description"] == "TBA" and row["Service"] == "DOL 100"
    assert row["Remarks"] == "PLC-1/Main rack" and unresolved == {}


def test_help_lists_the_paths() -> None:
    paths = dict(help_paths("load"))
    assert paths["<<LoadType.Name>>"] == "the load type's name" and "<<PlantArea.Parent.Tag>>" in paths
    assert paths["<<SuppliedFrom.LoadType.Code>>"] == "the panel it is supplied from's load type's code"
    assert "<<Parent.LoadType.Code>>" in dict(help_paths("runsheet")) and "<<Rack.System.Tag>>" in dict(help_paths("runsheet"))
