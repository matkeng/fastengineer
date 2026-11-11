# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Sample data: an invented small plant in every list of the app, so the whole chain
(imports -> Load List -> load types -> deliverables) can be tried on a new project.
Only lists that are still empty are filled; nothing existing is changed."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from workbench_core.deliverables import DELIVERABLE_TYPES, Deliverable, check_deliverable
from workbench_core.keylists import (EelList, EquipmentCode, EquipmentPackage, EquipmentPackageList, EquipmentType,
                                     InstrumentCode, PlantArea, PlantAreaList, check_code_list, check_eel,
                                     check_equipment_packages, check_load_types, check_plant_areas)
from workbench_core.keylists.plc import IoPoint, PlcCard, PlcList, PlcRack, PlcSystem, normalise_points
from workbench_core.mel import parse_csv
from workbench_core.mel.models import FieldMap
from workbench_core.refdata import (ColumnDef, EnumItem, EnumList, RefRow, RefTable, RefTree, TreeNode, check_enum,
                                    check_table_columns, check_tree, validate_row)

from .loadlist_api import current_rows
from .storage import get_deliverables, get_keylists, get_ref, get_store

router = APIRouter(prefix="/api/sample-data", tags=["sample data"])

MEL = b"""Tag,Area,Description,Type,kW,Voltage,Qty,Fed from
P-101,100,Feed pump A,DOL,7.5,415,1,MCC-1
P-102,100,Feed pump B,DOL,7.5,415,1,MCC-1
P-103,100,Booster pump,VSD,30,415,1,MCC-1
M-201,200,Mixer agitator,VSD,15,415,1,MCC-1
F-301,300,Exhaust fan,DOL,4,415,1,MCC-2
F-302,300,Supply fan,DOL,4,415,1,MCC-2
C-401,400,Air compressor,FEEDER,75,415,1,MCC-2
H-501,500,Tank heater,HTR,12,415,1,MCC-2
LP-601,600,Lighting panel,FEEDER,10,415,1,MCC-2
"""
MAPPING = {"tag": "Tag", "area": "Area", "desc": "Description", "load_type": "Type", "equip_type": "Type",
           "load_rating": "kW", "load_voltage": "Voltage", "equip_qty": "Qty", "supplied_from": "Fed from"}


def _cable(suffix: str, cable_type: str, cores: str, size: str, remarks: str = "") -> dict[str, str]:
    return {"Cable Number": f"<<Tag>>-{suffix}", "From": "<<SuppliedFrom>>", "From Description": "<<SuppliedFromDesc>>",
            "To": "<<Tag>>", "To Description": "<<Description>>", "Cable Type": cable_type, "Cores": cores, "Size": size,
            "Voltage": "0.6/1kV", "Remarks": remarks}


def _equipment(kind: str) -> dict[str, str]:
    return {"Tag": "<<Tag>>", "Description": "<<Description>>", "Equipment Type": kind, "Plant Area": "<<PlantArea>>",
            "Rating": "<<Rating>>", "Units": "<<Units>>", "Voltage": "<<Voltage>>", "Phases": "<<Phases>>",
            "Supplied From": "<<SuppliedFrom>>"}


def _io(suffix: str, description: str, signal: str, io_type: str) -> dict[str, str]:
    return {"Tag": f"<<Tag>>-{suffix}", "Description": f"<<Description>> {description}", "Signal": signal, "IO Type": io_type,
            "Plant Area": "<<PlantArea>>"}


def _instrument(suffix: str, description: str, kind: str, signal: str, io_type: str) -> dict[str, str]:
    return {"Tag": f"<<Tag>>-{suffix}", "Description": f"<<Description>> {description}", "Instrument Type": kind,
            "Plant Area": "<<PlantArea>>", "Service": "<<Description>>", "Signal": signal, "IO Type": io_type}


_RUN_IO = [_io("RUN", "running", "24 VDC", "DI"), _io("FLT", "fault", "24 VDC", "DI"), _io("STRT", "start command", "24 VDC", "DO")]
LOAD_TYPES = [
    {"id": "sdol", "code": "DOL", "name": "Direct on line motor starter", "rating_unit": "kW", "voltage": 415,
     "phases": "AC-3-phase", "from_value": "0.37", "to_value": "11", "std_drg": "E-STD-010", "bucket_type": "B1",
     "load_type": "Motor", "field_options": "LCS", "rows": {
         "cable_schedule": [_cable("P1", "Power", "3C+E", "2.5"), _cable("C1", "Control", "5+E", "1.5", "Local control station")],
         "equipment_list": [_equipment("Motor")],
         "instrument_list": [_instrument("HS", "local control station", "Hand switch", "24 VDC", "DI")],
         "plc_io_list": _RUN_IO}},
    {"id": "svsd", "code": "VSD", "name": "Variable speed drive", "rating_unit": "kW", "voltage": 415, "phases": "AC-3-phase",
     "from_value": "0.75", "to_value": "110", "std_drg": "E-STD-020", "bucket_type": "B3", "load_type": "Motor",
     "field_options": "LCS, Estop", "rows": {
         "cable_schedule": [_cable("P1", "VSD", "3C+3E", "6", "Screened VSD cable"), _cable("C1", "Control", "8+E", "1.5")],
         "equipment_list": [_equipment("Motor (VSD)")],
         "instrument_list": [_instrument("SIC", "speed control", "Speed controller", "4-20 mA", "AO")],
         "plc_io_list": _RUN_IO + [_io("SPD", "speed reference", "4-20 mA", "AO"), _io("SFB", "speed feedback", "4-20 mA", "AI")]}},
    {"id": "sfdr", "code": "FEEDER", "name": "Feeder (circuit breaker)", "rating_unit": "kW", "voltage": 415,
     "phases": "AC-3-phase+N", "std_drg": "E-STD-030", "bucket_type": "F1", "load_type": "Feeder", "rows": {
         "cable_schedule": [_cable("P1", "Power", "4C+E", "16")], "equipment_list": [_equipment("Feeder")],
         "plc_io_list": [_io("TRP", "breaker tripped", "24 VDC", "DI")]}},
    {"id": "shtr", "code": "HTR", "name": "Heater (contactor)", "rating_unit": "kW", "voltage": 415, "phases": "AC-3-phase",
     "std_drg": "E-STD-040", "bucket_type": "B2", "load_type": "Heater", "rows": {
         "cable_schedule": [_cable("P1", "Power", "3C+E", "4")], "equipment_list": [_equipment("Heater")],
         "instrument_list": [_instrument("TT", "temperature", "Temperature transmitter", "4-20 mA", "AI")],
         "plc_io_list": [_io("ON", "on", "24 VDC", "DI"), _io("CMD", "on command", "24 VDC", "DO")]}},
]


class Added(BaseModel):
    added: dict[str, int]  # what was filled -> how many
    skipped: list[str]  # what already had data and was left alone


@router.post("", response_model=Added)
def load_sample_data() -> Added:
    lists, ref, store, dl = get_keylists(), get_ref(), get_store(), get_deliverables()
    added: dict[str, int] = {}
    skipped: list[str] = []

    def fill(name: str, empty: bool, do) -> None:
        if empty:
            added[name] = do()
        else:
            skipped.append(name)

    def areas() -> int:
        a = lambda i, p, t, d, k, w="": PlantArea(id=i, parent_id=p, tag=t, description=d, area_type=k, wbs=w)  # noqa: E731
        nodes = [a("sw1", None, "W-1", "Process plant", "WBS", "1")]
        for n, d in enumerate(("Feed area", "Mixing area", "Filtration", "Compressor house", "Tank farm", "Utilities"), start=1):
            nodes.append(a(f"sa{n}", "sw1", f"{n}00", d, "Area", f"1.{n}"))
        nodes += [a("sb1", "sa1", "B-110", "Switchroom", "Building"), a("sr1", "sb1", "R-111", "MCC room", "Room"),
                  a("sp1", "sr1", "PNL-111", "PLC panel", "Panel")]
        lists.save_plant_areas(check_plant_areas(PlantAreaList(nodes=nodes)))
        return len(nodes)

    def packages() -> int:
        pk = lambda i, n, d, v, t: EquipmentPackage(id=i, number=n, description=d, vendor=v, package_type=t)  # noqa: E731
        items = [pk("sk1", "PKG-010", "LV switchgear and MCCs", "Acme Switchgear", "Vendor"),
                 pk("sk2", "PKG-020", "Process pumps", "Globex Pumps", "Large Mech"),
                 pk("sk3", "PKG-030", "Electrical installation", "Initech Electrical", "Installer")]
        types = [EquipmentType(package_id="sk1", name="Motor control centre"), EquipmentType(package_id="sk1", name="Distribution board"),
                 EquipmentType(package_id="sk2", name="Centrifugal pump", description="API 610")]
        lists.save_equipment_packages(check_equipment_packages(EquipmentPackageList(items=items, types=types)))
        return len(items) + len(types)

    def codes(list_id: str, model, rows: list[dict]) -> int:
        lists.save_code_list(list_id, check_code_list(rows, model, list_id))
        return len(rows)

    def load_types() -> int:
        lists.save_load_types(check_load_types(LOAD_TYPES))
        return len(LOAD_TYPES)

    def eel() -> int:
        known = {"equipment_code_id": {c.id for c in lists.code_list("equipment-codes").items},
                 "plant_area_id": {n.id for n in lists.plant_areas().nodes}, "load_type_id": {t.id for t in lists.load_types().items},
                 "supplied_from": {"eel/smsb"}}
        known |= {f: {p.id for p in lists.equipment_packages().items}
                  for f in ("vendor_package_id", "supplied_by_id", "installed_by_id", "terminated_by_id")}
        code = next(iter(sorted(known["equipment_code_id"])), "")
        area = "sr1" if "sr1" in known["plant_area_id"] else next(iter(sorted(known["plant_area_id"])), "")
        if not code or not area:
            return 0
        pkg = lambda p: p if p in known["vendor_package_id"] else None  # noqa: E731
        lt = "sfdr" if "sfdr" in known["load_type_id"] else None
        item = lambda i, tag, desc, amps, fed: {  # noqa: E731
            "id": i, "tag": tag, "description": desc, "equipment_code_id": "sc_mcc" if "sc_mcc" in known["equipment_code_id"] else code,
            "plant_area_id": area, "vendor_package_id": pkg("sk1"), "load_type_id": lt, "rating": amps, "rating_unit": "Amps",
            "voltage": 415, "phases": "AC-3-phase+N", "is_panel": True, "supplied_from": fed, "manufacturer": "Acme",
            "model_number": f"MX-{amps}", "supplied_by_id": pkg("sk1"), "installed_by_id": pkg("sk3"), "terminated_by_id": pkg("sk3")}
        items = [item("smsb", "MSB-1", "Main switchboard", 1600, "primary"), item("smcc1", "MCC-1", "Motor control centre 1", 630, "eel/smsb"),
                 item("smcc2", "MCC-2", "Motor control centre 2", 630, "eel/smsb")]
        lists.save_eel(check_eel(items, known))
        return len(items)

    def plc() -> int:
        area = "sp1" if any(n.id == "sp1" for n in lists.plant_areas().nodes) else None
        cards = [PlcCard(card_type_id=t) for t in ("net", "di16", "di16", "do16", "ai8", "ao8")]
        cards[1].points = [IoPoint(channel=0, tag="P-101-RUN", description="Feed pump A running"),
                           IoPoint(channel=1, tag="P-101-FLT", description="Feed pump A fault")]
        system = PlcSystem(tag="PLC-1", description="Process PLC", manufacturer="Acme Automation", model="CX-500",
                           racks=[PlcRack(tag="PLC-1-RK1", plant_area_id=area, rack_type_id="rack", description="Main rack", cards=cards)])
        fixed, _ = normalise_points(PlcList(systems=[system]), lists.catalogue())
        lists.save_plc(fixed)
        return len(cards)

    def mel() -> int:
        original, headers, rows, warnings = parse_csv(MEL)
        recipe = store.create_recipe("Sample plant MEL", "MEL")
        store.save_recipe(recipe.model_copy(update={"mapping": [FieldMap(field=f, column=c) for f, c in MAPPING.items()]}))
        rows.sort(key=lambda r: r["Tag"])
        store.add_revision(recipe.id, "sample-mel.csv", "csv", "Tag", original, headers, rows, warnings)
        return len(rows)

    def user_lists() -> int:
        e = ref.save_enum(check_enum(EnumList(name="Voltage levels", items=[
            EnumItem(code="LV", value="415 V", description="Low voltage"), EnumItem(code="ELV", value="24 V DC")])), create=True)
        ref.save_tree(check_tree(RefTree(name="Systems", nodes=[
            TreeNode(id="ss1", code="10", value="Process"), TreeNode(id="ss2", parent_id="ss1", code="11", value="Feed"),
            TreeNode(id="ss3", parent_id="ss1", code="12", value="Mixing")])), create=True)
        table = check_table_columns(RefTable(name="Spare parts", columns=[
            ColumnDef(name="Part", required=True, unique=True), ColumnDef(name="Qty", type="integer"),
            ColumnDef(name="Voltage", type="enum", enum_id=e.id)]), ref.enums())
        ref.save_table(table, create=True)
        for part, qty in (("Contactor 18 A", 4), ("Overload relay", 4)):
            values = validate_row(table, {table.columns[0].id: part, table.columns[1].id: qty, table.columns[2].id: "LV"},
                                  ref.enums(), ref.rows(table.id))
            ref.add_row(table.id, RefRow(values=values))
        return 3

    def deliverables() -> int:
        for n, kind in enumerate(DELIVERABLE_TYPES, start=1):
            d = Deliverable(type=kind, name=f"Sample {kind.lower()}", doc_number=f"E-LST-{n:03d}", doc_title=kind, source="project")
            dl.save(check_deliverable(d, dl.list(), set(), None), create=True)
        return len(DELIVERABLE_TYPES)

    ec = lambda i, c, n: {"id": i, "code": c, "name": n, "disciplines": ["E"]}  # noqa: E731
    ic = lambda c, n, p: {"code": c, "name": n, "plc_code": p}  # noqa: E731
    fill("Plant Areas", not lists.plant_areas().nodes, areas)
    fill("Equipment Packages", not lists.equipment_packages().items, packages)
    fill("Equipment Codes", not lists.code_list("equipment-codes").items, lambda: codes("equipment-codes", EquipmentCode, [
        ec("sc_mcc", "MCC", "Motor control centre"), ec("sc_db", "DB", "Distribution board"), ec("sc_mot", "MOT", "Motor")]))
    fill("Instrument Codes", not lists.code_list("instrument-codes").items, lambda: codes("instrument-codes", InstrumentCode, [
        ic("FT", "Flow transmitter", "AI"), ic("PT", "Pressure transmitter", "AI"), ic("TT", "Temperature transmitter", "AI"),
        ic("HS", "Hand switch", "DI"), ic("XV", "On/off valve", "DO")]))
    fill("Load Types", not lists.load_types().items, load_types)
    fill("Electrical Equipment List", not lists.eel().items, eel)
    fill("PLC List", not lists.plc().systems, plc)
    fill("List import (MEL)", not store.list_recipes(), mel)
    fill("Lists & tables", not (ref.enums() or ref.trees() or ref.tables()), user_lists)
    fill("Deliverables", not dl.list(), deliverables)
    current_rows()  # brings the Load List up to date, so its allocations are filled in
    return Added(added={k: v for k, v in added.items() if v}, skipped=skipped)
