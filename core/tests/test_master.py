# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
import pytest

from workbench_core.deliverables import Deliverable, check_deliverable, select_columns
from workbench_core.generators.models import BuildResult, BuildStats, OutputRow
from workbench_core.keylists import EquipmentType
from workbench_core.keylists.instrument_runsheet import InstrumentRunsheet, RunsheetRow
from workbench_core.keylists.loadgen import LISTS
from workbench_core.keylists.master import (MASTER_LISTS, MASTER_NAMES, generator_counts, instrument_rows, master_columns,
                                            master_list)
from workbench_core.refdata import RefValidationError

SIREN = EquipmentType(id="t1", package_id="p", name="Startup Siren - Single", rows={
    "instrument_list": [{"Tag": "<<MECH>>-HA<<SUF>>", "Description": "<<std>> at <<Mech>>", "Plant Area": "<<Area>>", "Range": "<<#2>>",
                         "Service": "<<PID>> <<VIA_MB>> <<Nope>>", "Remarks": "<<CONF>>/<<Rack>>/<<#40>>/<<Row>>"},
                        {"Tag": "<<MECH>>-HS", "Signal": "<<#1>>"}],
    "plc_io_list": [{"Tag": "<<MECH>>-HA", "Channel": "<<#1>>", "Rack": "<<Rack>>"}]})
SHEET = InstrumentRunsheet(rows=[
    RunsheetRow(id="r1", equipment_type_id="t1", plant_area_id="a1", parent_tag="3510-CR3001", suffix="A", pid="3510-P-PID-507",
                via_mb="**CV**-CPL1", confirmed=True, rack="1001", numbers=["10336", "0042"]),
    RunsheetRow(id="r2", equipment_type_id="t1", plant_area_id="a1", parent_tag="3510-CV3002", rack="1001", numbers=["10334"]),
    RunsheetRow(id="r3", equipment_type_id="gone", plant_area_id="a1", parent_tag="X")])


def _power(key: str, *rows: list) -> BuildResult:
    return BuildResult(header=list(LISTS[key].columns), rows=[OutputRow(cells=r, run_row_id="m/P-1") for r in rows],
                       stats=BuildStats(), unresolved_tokens=["<<Old>>"], unresolved_count=1)


def test_names_and_columns() -> None:
    assert MASTER_LISTS == ["cable_schedule", "equipment_list", "instrument_list", "plc_io_list"]
    assert MASTER_NAMES["plc_io_list"] == "Project Master IO List" and set(MASTER_NAMES) == set(MASTER_LISTS)
    assert master_columns("instrument_list")[-2:] == ["Generator", "Confirmed"] and master_columns("instrument_list")[0] == "Tag"


def test_the_instrument_generator_fills_in_the_equipment_types_rows() -> None:
    unresolved: dict[str, int] = {}
    rows = instrument_rows("instrument_list", SHEET, {"t1": SIREN}, {"a1": "3510"}, unresolved)
    assert [(r.cells[0], confirmed) for r, confirmed in rows] == [
        ("3510-CR3001-HAA", True), ("3510-CR3001-HS", True), ("3510-CV3002-HA", False), ("3510-CV3002-HS", False)]
    first = dict(zip(LISTS["instrument_list"].columns, rows[0][0].cells))
    assert (first["Description"], first["Plant Area"], first["Range"]) == ("Startup Siren - Single at 3510-CR3001", 3510, "0042")
    assert first["Service"] == "3510-P-PID-507 **CV**-CPL1 <<Nope>>" and first["Remarks"] == "TRUE/1001//1"  # a number it lacks: nothing
    assert rows[1][0].cells[LISTS["instrument_list"].columns.index("Signal")] == 10336 and unresolved == {"<<Nope>>": 2}
    assert (rows[0][0].run_row_id, rows[0][0].template_id, rows[1][0].template_seq) == ("runsheet/r1", "Startup Siren - Single", 2)
    assert instrument_rows("cable_schedule", SHEET, {"t1": SIREN}, {}) == []


def test_both_generators_fill_one_master_list() -> None:
    width = len(LISTS["plc_io_list"].columns)
    master = master_list("plc_io_list", _power("plc_io_list", ["P-1-RUN"] + [""] * (width - 1)), SHEET, {"t1": SIREN}, {"a1": "3510"})
    assert master.header == master_columns("plc_io_list") and len(master.rows) == 3
    assert [(r.cells[0], r.cells[-2], r.cells[-1]) for r in master.rows] == [
        ("P-1-RUN", "Power", "TRUE"), ("3510-CR3001-HA", "Instrument", "TRUE"), ("3510-CV3002-HA", "Instrument", "FALSE")]
    assert generator_counts(master) == {"Power": 1, "Instrument": 2} and master.unresolved_tokens == ["<<Old>>"]
    assert all(len(r.cells) == len(master.header) for r in master.rows)


def test_a_deliverable_chooses_and_orders_columns() -> None:
    master = master_list("plc_io_list", _power("plc_io_list"), SHEET, {"t1": SIREN}, {"a1": "3510"})
    cut = select_columns(master, ["confirmed", " Tag ", "Channel"])
    assert cut.header == ["Confirmed", "Tag", "Channel"] and cut.rows[0].cells == ["TRUE", "3510-CR3001-HA", 10336]
    assert select_columns(master, []) is master
    with pytest.raises(RefValidationError):
        select_columns(master, ["Tag", "Nope"])
    d = Deliverable(type="PLC I/O List", name="IO", source="project", columns=[" channel", "TAG", "Channel", ""])
    assert check_deliverable(d, [], set(), master.header, key_column="Tag").columns == ["Channel", "Tag"]
    for columns, text in ((["Channel"], "Keep the Tag column"), (["Tag", "Nope"], "Not columns of the content: Nope")):
        with pytest.raises(RefValidationError) as exc:
            check_deliverable(d.model_copy(update={"columns": columns}), [], set(), master.header, key_column="Tag")
        assert text in exc.value.fields["columns"]
