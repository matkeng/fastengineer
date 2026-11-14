# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Starter Coordination: NHP's Type 2 charts every project starts with, and a load's starter."""

from __future__ import annotations

from collections import Counter

import pytest

from workbench_core.keylists import workbooks as wbk
from workbench_core.keylists.load_calcs import apply_calcs, check_calcs
from workbench_core.keylists.loadgen import LISTS, generate
from workbench_core.keylists.loadlist import LoadListRow
from workbench_core.keylists.starters import (CHARTS, StarterList, chart_for, check_starters, default_starters, starter_fields,
                                              starter_for)
from workbench_core.keylists.tag_paths import Links
from workbench_core.keylists.validate import check_load_types
from workbench_core.mel.load_fields import LoadCalc, LoadField, default_load_fields
from workbench_core.refdata import RefValidationError

NHP = default_starters()
KW = [0.18, 0.25, 0.37, 0.55, 0.75, 1.1, 1.5, 2.2, 3, 4, 5.5, 7.5, 11, 15, 18.5, 22, 30, 37, 45, 55, 75]


def _row(chart: str, kw: float):
    return next(s for s in NHP if s.chart == chart and s.kw == kw)


def test_the_six_nhp_charts_as_printed() -> None:
    assert Counter(s.chart for s in NHP) == {c: 21 for c in CHARTS}
    assert all([s.kw for s in NHP if s.chart == c] == KW for c in CHARTS)
    assert {s.chart: s.fault_ka for s in NHP} == {c: ka for c, (ka, _) in CHARTS.items()}
    assert len({s.id for s in NHP}) == 126
    a = _row("ECH64.2", 45)  # p17
    assert (a.flc, a.cb, a.cb_amps, a.el_setting, a.contactor, a.overload, a.range_min, a.range_max, a.inst_trip, a.min_trip, a.note) == (
        80, "ZS250M / 160A", 160, "30mA – 3A", "CA9-190", "CEP7-1EF GE", 20, 100, 2080, 20.8, "*")
    assert _row("ECH54.2", 5.5).cb == "ZS125M / 20A"  # printed "S5.5" on p14
    assert (_row("ECH64.2", 75).overload, _row("ECH64.2", 75).note) == ("CTKIT400A", "^")
    b = _row("RECH64.24", 15)  # p19
    assert (b.contactor, b.overload, b.range_min, b.range_max, b.inst_trip) == ("100-C43", "193 E3-63-24D-I-60A-#-ETR", 6, 60, 600)
    assert _row("ECH64.13", 37).contactor == "CA7-85" and _row("ECH54.12", 0.18).min_trip == 320


def test_a_load_gets_its_charts_row() -> None:
    assert chart_for("", "ECH64.2") == "ECH64.2" and chart_for("RECH64.24", "ECH64.2") == "RECH64.24"
    assert chart_for("none", "ECH64.2") is None
    assert starter_for(4.2, "kW", "ECH64.2", NHP).kw == 5.5
    assert starter_for(5.5, "kW", "ECH64.2", NHP).kw == 5.5
    assert starter_for(10, "HP", "ECH64.2", NHP).kw == 7.5  # 7.457 kW
    assert starter_for(20, "Amps", "ECH64.2", NHP).flc == 22
    assert starter_for(80, "kW", "ECH64.2", NHP) is None and starter_for(5, "kW", None, NHP) is None
    assert starter_for(5, "kW", "nope", NHP) is None and starter_for("", "kW", "ECH64.2", NHP) is None
    f = starter_fields(starter_for(30, "kW", "ECH64.2", NHP))
    assert (f["cb"], f["contactor"], f["overload"], f["range"], f["insttrip"], f["faultka"]) == (
        "ZS125M / 100A", "CA7-72", "CEP7-1EF GE", "20 – 100", 1200, 65)
    assert set(starter_fields(None).values()) == {""}


def test_starter_rows_are_checked() -> None:
    ok = check_starters([{"chart": "MINE", "kw": "4", "cb": "X / 16A"}], "mine")
    assert ok.items[0].cb_amps == 16 and ok.default_chart == "MINE"
    with pytest.raises(RefValidationError) as exc:
        check_starters([{"id": "a", "chart": "", "kw": "0"}, {"id": "b", "chart": "C", "kw": "4"}, {"id": "c", "chart": "c", "kw": "4"},
                        {"id": "d", "chart": "C", "kw": "5", "flc": "lots", "inst_trip": "-1"}], "Z")
    assert set(exc.value.fields) == {"a.chart", "a.kw", "c.kw", "d.flc", "d.inst_trip", "default_chart"}


def test_the_workbook_round_trip() -> None:
    sheets = wbk.export_starters(StarterList(items=NHP, default_chart="RECH64.24"))
    as_read = {t.casefold(): [{str(h).casefold(): ("" if v is None else str(v)) for h, v in zip(rows[0], r)} for r in rows[1:]]
               for t, rows in sheets}
    parsed = wbk.import_starters(as_read, StarterList(items=NHP))
    back = check_starters(parsed.payload["items"], parsed.payload["default_chart"])
    assert back.default_chart == "RECH64.24" and back.items == NHP


def test_template_rows_and_calculations_reach_the_starter() -> None:
    types = check_load_types([
        {"id": "t1", "code": "DOL", "name": "DOL", "rating_unit": "kW", "voltage": "415", "phases": "AC-3-phase",
         "rows": {"equipment_list": [{"Tag": "<<Tag>>", "Model": "<<Starter.CB>> <<Starter.Contactor>>",
                                      "Rating": "<<Starter.InstTrip>>", "Remarks": "<<Starter.Chart>> <<Starter.Overload>> <<Starter.Range>>"}]}},
        {"id": "t2", "code": "DOLR", "name": "DOL (A-B)", "rating_unit": "kW", "voltage": "415", "phases": "AC-3-phase",
         "starter_chart": "RECH64.24", "rows": {"equipment_list": [{"Tag": "<<Tag>>", "Model": "<<Starter.Contactor>>"}]}},
        {"id": "t3", "code": "VSD", "name": "VSD", "rating_unit": "kW", "voltage": "415", "phases": "AC-3-phase",
         "starter_chart": "None", "rows": {"equipment_list": [{"Tag": "<<Tag>>", "Model": "<<Starter.Contactor>>"}]}}])
    assert types.items[1].starter_chart == "RECH64.24"
    loads = [LoadListRow(recipe_id="m", key=k, source="MEL", target="MEL", load_type_id=t,
                         values={"tag": k, "load_rating": kw, "load_units": "kW"})
             for k, t, kw in (("P-1", "t1", 11), ("P-2", "t2", 18), ("P-3", "t3", 11))]
    lt = {t.id: t for t in types.items}
    starters = StarterList(items=NHP)
    eq = generate("equipment_list", loads, lt, {}, links=Links(load_types=types.items, loads=loads, starters=starters))
    rows = {r.cells[0]: dict(zip(LISTS["equipment_list"].columns, r.cells)) for r in eq.rows}
    assert rows["P-1"]["Model"] == "ZS125M / 32A CA7-30" and rows["P-1"]["Rating"] == 384
    assert rows["P-1"]["Remarks"] == "ECH64.2 CEP7-1EF ED 5.4 – 27"
    assert rows["P-2"]["Model"] == "100-C43" and rows["P-3"]["Model"] in ("", None)
    calc = LoadField(key="trip_x", label="Trip x", kind="calc", calc=LoadCalc(formula="<<Starter.InstTrip>> / <<Starter.FLC>>", decimals=1))
    fields = default_load_fields().model_copy(update={"fields": [*default_load_fields().fields, calc]})
    check_calcs(fields)
    apply_calcs(loads[:1], fields, lt, {}, starters=starters)
    assert loads[0].values["trip_x"] == round(384 / 22, 1)


def test_a_load_only_gets_a_starter_of_its_own_voltage() -> None:
    from workbench_core.keylists.motors import default_motors
    from workbench_core.keylists.starters import chart_rows, starter_problems

    assert {s.voltage for s in NHP} == {400}  # the charts are printed for 400/415 V
    assert starter_for(11, "kW", "ECH64.2", NHP, 415).kw == 11 and starter_for(11, "kW", "ECH64.2", NHP, 400).kw == 11
    assert starter_for(11, "kW", "ECH64.2", NHP).kw == 11 and starter_for(11, "kW", "ECH64.2", NHP, "").kw == 11  # no voltage: as before
    for volts in (690, 240, 433):  # a 400 V chart is not for these
        assert starter_for(11, "kW", "ECH64.2", NHP, volts) is None and chart_rows("ECH64.2", NHP, volts) == []
    # a project's own 690 V rows of the same chart are used for a 690 V load, and only for it
    own = check_starters([s.model_dump() for s in NHP] + [{"chart": "ECH64.2", "kw": "11", "voltage": "690", "cb": "XS125 / 20A",
                                                         "range_min": "10", "range_max": "16"}])
    assert starter_for(11, "kW", "ECH64.2", own.items, 690).cb == "XS125 / 20A"
    assert starter_for(11, "kW", "ECH64.2", own.items, 415).cb == "ZS125M / 32A"
    # the same chart and kW twice is refused per voltage; a voltage outside every range is refused; blank is 400
    with pytest.raises(RefValidationError) as exc:
        check_starters([{"id": "a", "chart": "X", "kw": "11"}, {"id": "b", "chart": "X", "kw": "11", "voltage": "400"},
                        {"id": "c", "chart": "X", "kw": "11", "voltage": "690"}, {"id": "d", "chart": "X", "kw": "15", "voltage": "500"}])
    assert set(exc.value.fields) == {"b.kw", "d.voltage"} and "500 V is not" in exc.value.fields["d.voltage"]

    def issues(volts: str, kw: float, poles=4, formula="<<Starter.CB>>") -> tuple[object, list[str]]:
        types = check_load_types([{"id": "t1", "code": "DOL", "name": "DOL", "rating_unit": "kW", "voltage": volts, "phases": "AC-3-phase"}])
        load = LoadListRow(recipe_id="m", key="P-1", source="MEL", target="MEL", load_type_id="t1",
                           values={"tag": "P-1", "load_rating": kw, "load_units": "kW", "poles": poles})
        calc = LoadField(key="x", label="X", kind="calc", calc=LoadCalc(formula=formula))
        fields = default_load_fields().model_copy(update={"fields": [*default_load_fields().fields, calc]})
        apply_calcs([load], fields, {t.id: t for t in types.items}, {}, motors=default_motors(), starters=StarterList(items=NHP))
        return load.values["x"], [i["message"] for i in load.calc_issues]

    assert issues("415", 11) == ("ZS125M / 32A", [])
    assert issues("690", 11) == ("", ["No starter is matched: chart ECH64.2 is for 380-415 V, the load is 690 V"])
    assert issues("690", 11, formula="<<rating>> * 2") == (22, [])  # only where the starter is used
    # the overload must be able to be set to the motor's current: 0.37 kW 4-pole is 0.96 A, the range starts at 1 A
    value, messages = issues("415", 0.37)
    assert value and messages == ["The motor's full load current (0.96 A at 415 V) is outside the overload's setting range (1 to 5 A)"]
    assert starter_problems(415, "", StarterList(items=NHP), _row("ECH64.2", 11), 20.4, 415) == []
    assert starter_problems(415, "None", StarterList(items=NHP), None) == []  # a load type with no starter


def test_the_workbook_keeps_the_voltage_and_reads_one_without_it() -> None:
    own = check_starters([{"id": "a", "chart": "X", "kw": "11", "voltage": "690"}, {"id": "b", "chart": "X", "kw": "11"}])
    sheets = dict(wbk.export_starters(own))
    head = sheets["Starter Coordination"][0]
    assert "Voltage" in head and [r[head.index("Voltage")] for r in sheets["Starter Coordination"][1:]] == [690, 400]
    back = wbk.import_starters(wbk.read_sheets(wbk.write_sheets(wbk.export_starters(own))), own)
    assert [(i["id"], i["voltage"]) for i in back.payload["items"]] == [("a", "690"), ("b", "400")]
    # a workbook from before the Voltage column: every row is a 400 V row, and keeps its id
    old = [(n, [[c for c in row[:head.index("Voltage")] + row[head.index("Voltage") + 1:]] for row in grid] if n == "Starter Coordination" else grid)
           for n, grid in wbk.export_starters(check_starters([{"id": "b", "chart": "X", "kw": "11"}]))]
    back = wbk.import_starters(wbk.read_sheets(wbk.write_sheets(old)), own)
    assert [(i["id"], i["voltage"]) for i in back.payload["items"]] == [("b", "")]
    assert check_starters(back.payload["items"]).items[0].voltage == 400
