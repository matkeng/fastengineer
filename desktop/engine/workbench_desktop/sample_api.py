# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Sample data: an invented small plant in every list of the app, so the whole chain
(imports -> Load List -> load types -> deliverables) can be tried on a new project.
Only lists that are still empty are filled; nothing existing is changed."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from workbench_core.deliverables import DELIVERABLE_TYPES, PANEL_TYPE, Deliverable, check_deliverable
from workbench_core.keylists.distribution_panels import (DistributionPanel, DistributionPanelList, PanelDivider, PanelEntry,
                                                         PoleValues, auto_place, check_panels)
from workbench_core.keylists import (EelList, EquipmentCode, EquipmentPackage, EquipmentPackageList, EquipmentType,
                                     InstrumentCode, PlantArea, PlantAreaList, check_code_list, check_eel,
                                     check_equipment_packages, check_load_types, check_plant_areas)
from workbench_core.keylists.plc import IoPoint, PlcCard, PlcList, PlcRack, PlcSystem, normalise_points
from workbench_core.mel import parse_csv
from workbench_core.refdata import RefValidationError, name_key
from workbench_core.mel.models import FieldMap
from workbench_core.refdata import (ColumnDef, EnumItem, EnumList, RefRow, RefTable, RefTree, TreeNode, check_enum,
                                    check_table_columns, check_tree, validate_row)

from .loadlist_api import current_rows
from .storage import get_deliverables, get_keylists, get_loadlist, get_ref, get_store

router = APIRouter(prefix="/api/sample-data", tags=["sample data"])
SAMPLE_PANEL = "sdp1"

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


def _power(cable_type: str, cores: str, remarks: str = "") -> dict[str, str]:
    """The load's power cable(s): one row per cable, each looked up in Cable Types from the load's cable details."""
    return _cable("P<<CableNo>>", cable_type, cores, "<<CableSize>>", remarks) | {
        "Repeat": "Per power cable", "Voltage": "<<CableVoltage>>", "Length (m)": "<<CableLength>>", "Route": "<<Phase>>"}


#: The sample loads' cable details: tag -> (size, insulation, length, parallel, single core?, earth size)
CABLES = {"P-101": ("2.5", "PVC", 45, 1, False, ""), "P-102": ("2.5", "PVC", 48, 1, False, ""),
          "P-103": ("10", "XLPE", 60, 1, False, ""), "M-201": ("6", "XLPE", 85, 1, False, ""),
          "F-301": ("2.5", "PVC", 110, 1, False, ""), "F-302": ("2.5", "PVC", 115, 1, False, ""),
          "C-401": ("50", "XLPE", 140, 2, False, ""), "H-501": ("4", "PVC", 95, 1, False, ""),
          "LP-601": ("6", "PVC", 160, 1, False, ""), "MSB-1": ("300", "XLPE", 25, 2, True, "120"),
          "MCC-1": ("240", "XLPE", 15, 1, False, ""), "MCC-2": ("240", "XLPE", 20, 1, False, "")}


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
         "cable_schedule": [_power("Power", "3C+E"), _cable("C1", "Control", "5+E", "1.5", "Local control station")],
         "equipment_list": [_equipment("Motor")],
         "instrument_list": [_instrument("HS", "local control station", "Hand switch", "24 VDC", "DI")],
         "plc_io_list": _RUN_IO}},
    {"id": "svsd", "code": "VSD", "name": "Variable speed drive", "rating_unit": "kW", "voltage": 415, "phases": "AC-3-phase",
     "from_value": "0.75", "to_value": "110", "std_drg": "E-STD-020", "bucket_type": "B3", "load_type": "Motor",
     "field_options": "LCS, Estop", "rows": {
         "cable_schedule": [_power("VSD", "3C+3E", "Screened VSD cable"), _cable("C1", "Control", "8+E", "1.5")],
         "equipment_list": [_equipment("Motor (VSD)")],
         "instrument_list": [_instrument("SIC", "speed control", "Speed controller", "4-20 mA", "AO")],
         "plc_io_list": _RUN_IO + [_io("SPD", "speed reference", "4-20 mA", "AO"), _io("SFB", "speed feedback", "4-20 mA", "AI")]}},
    {"id": "sfdr", "code": "FEEDER", "name": "Feeder (circuit breaker)", "rating_unit": "kW", "voltage": 415,
     "phases": "AC-3-phase+N", "std_drg": "E-STD-030", "bucket_type": "F1", "load_type": "Feeder", "rows": {
         "cable_schedule": [_power("Power", "4C+E")], "equipment_list": [_equipment("Feeder")],
         "plc_io_list": [_io("TRP", "breaker tripped", "24 VDC", "DI")]}},
    {"id": "shtr", "code": "HTR", "name": "Heater (contactor)", "rating_unit": "kW", "voltage": 415, "phases": "AC-3-phase",
     "std_drg": "E-STD-040", "bucket_type": "B2", "load_type": "Heater", "rows": {
         "cable_schedule": [_power("Power", "3C+E")], "equipment_list": [_equipment("Heater")],
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
                 EquipmentType(package_id="sk2", name="Centrifugal pump", description="API 610", rows={
                     # for the Instrument generator: what each runsheet row of this type adds, filled in from the row
                     "instrument_list": [{"Tag": "<<MECH>>-PT<<SUF>>", "Description": "<<MECH>> discharge pressure",
                                          "Instrument Type": "Pressure transmitter", "Plant Area": "<<Area>>", "Service": "<<PID>>",
                                          "Signal": "4-20 mA", "IO Type": "AI"}],
                     "plc_io_list": [{"Tag": "<<MECH>>-PT<<SUF>>", "Description": "<<MECH>> discharge pressure", "Signal": "4-20 mA",
                                      "IO Type": "AI", "Rack": "<<Rack>>", "Channel": "<<#1>>", "Plant Area": "<<Area>>"}]})]
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

    def deliverables() -> int:
        panels = {p.id for p in lists.distribution_panels().panels}
        done = 0
        for n, kind in enumerate(DELIVERABLE_TYPES, start=1):
            d = Deliverable(type=kind, name=f"Sample {kind.lower()}", doc_number=f"E-LST-{n:03d}", doc_title=kind, source="project")
            if kind == PANEL_TYPE:  # the schedule of the sample panel, if this run made it
                if SAMPLE_PANEL not in panels:
                    continue
                d = d.model_copy(update={"source": "panel", "panel_id": SAMPLE_PANEL})
            dl.save(check_deliverable(d, dl.list(), set(), None, panels), create=True)
            done += 1
        return done

    def drawings() -> int:
        """A few drawings of the sample plant. (Choices the project's Enums no longer have are left blank.)"""
        from workbench_core.keylists.drawing_list import check_drawings
        from workbench_core.keylists.enums import lookup
        enums = lists.enums()
        has = {"discipline": lookup(enums.disciplines), "drawing_type": lookup(enums.drawing_types), "status": lookup(enums.drawing_statuses)}
        want = [("100-E-SLD-001", "MCC-1", "Single line diagram", "E", "Single Line Diagram", "B", "IFC", "14/03/2026", "MCC-1"),
                ("100-E-SCH-101", "Feed pump A", "Schematic diagram", "E", "Schematic", "A", "IFR", "02/04/2026", "P-101"),
                ("100-PR-PID-001", "Feed area", "Piping and instrument diagram", "PR", "P&ID", "0", "IFA", "20/02/2026", "P-101, P-102"),
                ("100-E-LAY-001", "Switchroom", "Equipment layout", "E", "Layout", "A", "Draft", "", "MCC-1, MCC-2")]
        rows = []
        for number, title_1, title_2, discipline, kind, rev, status, issued, equipment in want:
            row = {"number": number, "project_name": "Sample plant", "title_1": title_1, "title_2": title_2, "discipline": discipline,
                   "drawing_type": kind, "revision": rev, "status": status, "issue_date": issued, "equipment_reference": equipment,
                   "scope": "Detailed design", "hyperlink": f"https://dms.example.com/drawings/{number}"}
            rows.append({k: v for k, v in row.items() if k not in has or name_key(v) in has[k]})
        lists.save_drawing_list(check_drawings(rows, enums))
        return len(rows)

    def documents() -> int:
        """A few documents of the sample plant. (Choices the project's Enums no longer have are left blank.)"""
        from workbench_core.keylists.drawing_list import DOCUMENTS, check_drawings
        from workbench_core.keylists.enums import lookup
        enums = lists.enums()
        has = {"discipline": lookup(enums.disciplines), "document_type": lookup(enums.document_types), "status": lookup(enums.drawing_statuses)}
        want = [("100-E-SCH-001", "Cable schedule", "E", "Schedule", "B", "IFC", "10/02/2026", "MCC-1, MCC-2"),
                ("100-E-LST-001", "Electrical equipment list", "E", "List", "A", "IFR", "05/03/2026", ""),
                ("100-I-DS-001", "Pressure transmitter datasheet", "I", "Datasheet", "0", "IFA", "", "P-101")]
        rows = []
        for number, title, discipline, kind, rev, status, issued, equipment in want:
            row = {"number": number, "project_name": "Sample plant", "title": title, "discipline": discipline, "document_type": kind,
                   "revision": rev, "status": status, "issue_date": issued, "equipment_reference": equipment, "scope": "Detailed design",
                   "hyperlink": f"https://dms.example.com/documents/{number}"}
            rows.append({k: v for k, v in row.items() if k not in has or name_key(v) in has[k]})
        lists.save_document_list(check_drawings(rows, enums, DOCUMENTS))
        return len(rows)

    def runsheet() -> int:
        """A few rows for the Instrument generator: a pressure transmitter set on each pump."""
        from workbench_core.keylists.instrument_runsheet import TypedRow

        from .instrument_runsheet_api import checked, known
        k = known()
        if not ({"Centrifugal pump"} <= {n for _, n in k.types} and {"100"} <= {t for _, t in k.areas}):
            return 0
        want = [("P-101", "A", "100-P-PID-001", "TRUE", "1001", "10101"), ("P-102", "B", "100-P-PID-001", "TRUE", "1001", "10102"),
                ("P-103", "", "100-P-PID-002", "FALSE", "1001", "10103")]
        rows = [TypedRow(cells=["Centrifugal pump", "100", tag, suffix, pid, "", conf, rack, number])
                for tag, suffix, pid, conf, rack, number in want if tag in k.parents]
        try:
            lists.save_instrument_runsheet(checked(rows, k))
        except RefValidationError:
            return 0
        return len(rows)

    def panels() -> int:
        """MCC-2's schedule: its loads on the first ways, then a spare breaker, an RCD and the
        lighting control circuit, and two spare breakers behind the lighting contactor."""
        loads = {r.ref(): r for r in rows}
        if not (loads.get("eel/smcc2") and loads["eel/smcc2"].is_panel):
            return 0
        types = {t.id: t for t in lists.load_types().items}
        panel = auto_place(DistributionPanel(id=SAMPLE_PANEL, load_ref="eel/smcc2", ways=12, isolator_rating=630, upstream_cb=630),
                           loads, types)
        for e in panel.entries:
            e.rows = [PoleValues(cb_rating=63) for _ in e.rows]
        way = max((e.way for e in panel.entries), default=0) + 1
        if way + 1 > 8:
            return 0
        panel.entries += [
            PanelEntry(way=way, pole="R", poles=3, kind="spare_cb", rows=[PoleValues(cb_rating=32) for _ in range(3)]),
            PanelEntry(way=way + 1, pole="R", kind="rcd", description="RCD RTS module", rows=[PoleValues(cb_rating=6, qty=1, watts_each=78)]),
            PanelEntry(way=way + 1, pole="W", kind="light_control", description="Lighting control circuit",
                       rows=[PoleValues(cb_rating=6, qty=1, watts_each=344)]),
            PanelEntry(way=9, pole="R", kind="other", description="Walkway lighting circuit 1", load_type="Light - Walkway",
                       rows=[PoleValues(cb_rating=16, qty=12, watts_each=33)]),
            PanelEntry(way=9, pole="W", kind="spare_cb", rows=[PoleValues(cb_rating=16)]),
            PanelEntry(way=10, pole="R", kind="other", description="Walkway lighting circuit 2", load_type="Light - Walkway",
                       rows=[PoleValues(cb_rating=16, qty=14, watts_each=22)])]
        panel.dividers = [PanelDivider(before_way=9, label="Lighting Contactor")]
        doc, errors = check_panels(DistributionPanelList(panels=[panel]), loads)
        if errors:
            return 0
        lists.save_distribution_panels(doc)
        return 1

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
    rows, _, _ = current_rows()  # brings the Load List up to date, so its allocations are filled in
    fill("Distribution Panels", not lists.distribution_panels().panels, panels)
    fill("Instrument Runsheet", not lists.instrument_runsheet().rows, runsheet)
    fill("Drawing List", not lists.drawing_list().items, drawings)
    fill("Document List", not lists.document_list().items, documents)
    fill("Deliverables", not dl.list(), deliverables)
    if "List import (MEL)" in added or "Electrical Equipment List" in added:
        done = 0
        for r in rows:
            c = CABLES.get(r.tag())
            mine = "Electrical Equipment List" if r.recipe_id == "eel" else "List import (MEL)"
            if c and not r.cable_size and mine in added:
                get_loadlist().allocate([(r.recipe_id, r.key)], {
                    "cable_size": c[0], "cable_insulation": c[1], "cable_length": float(c[2]), "cable_parallel": c[3],
                    "cable_construction": "Single core" if c[4] else "Multicore", "earth_size": c[5]}, {})
                done += 1
        if done:
            added["Cable details (Load List)"] = done
    return Added(added={k: v for k, v in added.items() if v}, skipped=skipped)
