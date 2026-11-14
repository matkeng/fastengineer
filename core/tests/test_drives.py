# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Drive Data: the PowerFlex 755TS range every project starts with, and matching a load to a drive."""

from __future__ import annotations

from collections import Counter

import pytest

from workbench_core.keylists.drives import check_drives, default_drives, drive_for, drive_for_load, voltage_class
from workbench_core.keylists.load_calcs import apply_calcs, check_calcs
from workbench_core.keylists.loadgen import LISTS, generate
from workbench_core.keylists.loadlist import LoadListRow
from workbench_core.keylists.motors import default_motors
from workbench_core.keylists.tag_paths import Links
from workbench_core.keylists.validate import check_load_types
from workbench_core.mel.load_fields import LoadCalc, LoadField, default_load_fields
from workbench_core.refdata import RefValidationError

PF = default_drives()


def _one(cat: str, volts: int, enc: str = "Open"):
    return next(d for d in PF if d.cat_no == cat and d.voltage == volts and d.enclosure == enc)


def test_the_755ts_tables_as_printed() -> None:
    # pages 8-21: rows per voltage and enclosure, and the frame sizes of each table
    assert Counter((d.voltage, d.enclosure) for d in PF) == {
        (240, "Open"): 26, (240, "IP54"): 21, (240, "Flange"): 13, (400, "Open"): 32, (400, "IP54"): 22, (400, "Flange"): 15,
        (480, "Open"): 32, (480, "IP54"): 22, (480, "Flange"): 15, (600, "Open"): 28, (600, "IP54"): 27, (600, "Flange"): 12,
        (690, "Open"): 16, (690, "IP54"): 16}
    frames = Counter((d.voltage, d.enclosure, d.frame) for d in PF)
    assert [frames[(240, "Open", f)] for f in "1234567"] == [5, 6, 3, 2, 2, 5, 3]
    assert [frames[(400, "Open", f)] for f in ("1", "2", "3", "4", "5", "6", "7", "7A")] == [6, 7, 4, 3, 2, 4, 4, 2]
    assert [frames[(600, "IP54", f)] for f in "34567"] == [8, 2, 1, 13, 3] and frames[(690, "Open", "7")] == 3
    assert len({d.id for d in PF}) == len(PF) == 297
    # a 240 V row: amps at 240 V and (208 V), Hp and (kW), page 8
    b = _one("20G2ANB360JA0NNNNN", 240)
    assert (b.frame, b.nd_amps, b.nd_amps_208, b.nd_amps_1min, b.nd_amps_3s, b.nd_hp, b.nd_kw) == ("7", 360, 414, 396, 540, 150, 110)
    assert (b.hd_amps, b.hd_amps_208, b.hd_amps_3s, b.hd_amps_3s_208, b.hd_hp, b.hd_kw) == (312, 414, 561.6, 646.2, 125, 90)
    c = _one("20G2ANC650JA0NNNNN", 400)  # 400 V frame 7A, page 11: kW
    assert (c.frame, c.nd_amps, c.nd_kw, c.hd_amps, c.hd_amps_3s, c.hd_kw, c.nd_hp) == ("7A", 650, 355, 540, 972, 315, None)
    d = _one("20G21NE1P7JA0NNNNN", 600)  # 600 V, page 17: Hp, HD 1 min 1.4 as printed
    assert (d.frame, d.nd_amps, d.nd_hp, d.hd_amps_1min) == ("3", 1.7, 1, 1.4)
    # frames 6 and 7 are dual-voltage: one catalog number at 600 V and at 690 V
    assert {x.voltage for x in PF if x.cat_no == "20G2ANE012JA0NNNNN" or x.cat_no == "20G2ANF012JA0NNNNN"} == {600, 690}


def test_a_load_gets_the_smallest_drive_that_fits() -> None:
    assert voltage_class(415) == 400 and voltage_class(208) == 240 and voltage_class(690) == 690 and voltage_class(1000) is None
    assert drive_for(415, 13.5, None, "", "", PF).cat_no == "20G21RC015JA0NNNNN"  # 15.4 A, frame 1 before the same in frame 2
    hd = drive_for(415, 13.5, None, "Heavy", "", PF)
    assert hd.hd_amps >= 13.5 and hd.nd_amps > 15.4
    assert drive_for(415, 13.5, None, "", "IP54", PF).cat_no == "20G21GC015JA0NNNNN"
    assert drive_for(415, 13.5, None, "", "flange", PF).cat_no == "20G21FC015JA0NNNNN"
    assert drive_for(208, 5, None, "", "", PF).nd_amps_208 >= 5  # at 208 V the amps in parentheses
    assert drive_for(415, None, 37, "", "", PF).nd_kw == 37  # no current: on power
    assert drive_for(415, 2000, None, "", "", PF) is None and drive_for(100, 5, None, "", "", PF) is None
    assert drive_for_load(10, "HP", 480, None, "", "", PF).nd_hp == 10


def test_drive_rows_are_checked() -> None:
    ok = check_drives([{"cat_no": "X", "voltage": "400", "enclosure": "ip54", "nd_amps": "10"},
                       {"cat_no": "X", "voltage": "690", "enclosure": "Open", "nd_amps": "10"}])
    assert [d.enclosure for d in ok] == ["IP54", "Open"]
    with pytest.raises(RefValidationError) as exc:
        check_drives([{"id": "a", "cat_no": "X", "voltage": "415", "nd_amps": ""}, {"id": "b", "cat_no": "x", "voltage": "400", "nd_amps": "5"},
                      {"id": "c", "cat_no": "x", "voltage": "400", "nd_amps": "5", "hd_amps": "lots"}])
    assert set(exc.value.fields) == {"a.voltage", "a.nd_amps", "b.cat_no", "c.cat_no", "c.hd_amps"}


def test_template_rows_and_calculations_reach_the_drive() -> None:
    types = check_load_types([{"id": "t1", "code": "VSD", "name": "VSD", "rating_unit": "kW", "voltage": "415", "phases": "AC-3-phase",
                               "rows": {"equipment_list": [{"Tag": "<<Tag>>", "Model": "<<Drive.CatNo>> F<<Drive.Frame>>",
                                                            "Rating": "<<Drive.Amps>>", "Remarks": "<<Drive.Duty>> <<Drive.Enclosure>>"}]}}])
    loads = [LoadListRow(recipe_id="m", key=k, source="MEL", target="MEL", load_type_id="t1",
                         values={"tag": k, "load_rating": kw, "load_units": "kW", "poles": 4, "drive_duty": duty, "drive_enclosure": enc})
             for k, kw, duty, enc in (("P-1", 7.5, "", ""), ("P-2", 7.5, "HD", "IP54"), ("P-3", 400, "", ""))]
    lt = {t.id: t for t in types.items}
    eq = generate("equipment_list", loads, lt, {}, links=Links(load_types=types.items, loads=loads, motors=default_motors(), drives=PF))
    rows = {r.cells[0]: dict(zip(LISTS["equipment_list"].columns, r.cells)) for r in eq.rows}
    assert (rows["P-1"]["Model"], rows["P-1"]["Rating"], rows["P-1"]["Remarks"]) == ("20G21RC015JA0NNNNN F1", 15.4, "ND Open")
    assert rows["P-2"]["Remarks"] == "HD IP54" and rows["P-2"]["Rating"] >= 13.5
    calc = LoadField(key="drive_margin", label="Drive margin", kind="calc", calc=LoadCalc(formula="<<Drive.Amps>> - <<Motor.FLC>>", decimals=1))
    fields = default_load_fields().model_copy(update={"fields": [*default_load_fields().fields, calc]})
    check_calcs(fields)
    apply_calcs(loads[:1], fields, lt, {}, motors=default_motors(), drives=PF)
    assert loads[0].values["drive_margin"] == round(15.4 - 13.5, 1)


def test_the_motors_current_is_taken_at_the_loads_voltage() -> None:
    from workbench_core.keylists.drives import flc_at
    assert flc_at(55.4, 415, 415) == 55.4
    assert flc_at(55.4, 415, 240) == pytest.approx(95.8, abs=0.05) and flc_at(55.4, 415, 690) == pytest.approx(33.3, abs=0.05)
    assert flc_at(55.4, None, 240) == 55.4 and flc_at(55.4, 415, "") == 55.4 and flc_at(None, 415, 240) is None

    def drive_amps(volts: str) -> tuple[object, list[dict]]:
        types = check_load_types([{"id": "t1", "code": "VSD", "name": "VSD", "rating_unit": "kW", "voltage": volts, "phases": "AC-3-phase"}])
        load = LoadListRow(recipe_id="m", key="P-1", source="MEL", target="MEL", load_type_id="t1",
                           values={"tag": "P-1", "load_rating": 30, "load_units": "kW", "poles": 4})
        calc = LoadField(key="drive_amps", label="Drive amps", kind="calc", calc=LoadCalc(formula="<<Drive.Amps>>"))
        fields = default_load_fields().model_copy(update={"fields": [*default_load_fields().fields, calc]})
        apply_calcs([load], fields, {t.id: t for t in types.items}, {}, motors=default_motors(), drives=PF)
        return load.values["drive_amps"], load.calc_issues

    # a 30 kW 4-pole motor: 55.4 A at 415 V
    assert drive_amps("415")[0] >= 55.4
    assert drive_amps("240")[0] >= 95.8  # was a 70 A drive, picked on the 415 V current
    assert drive_amps("690")[0] < 55.4   # 33.3 A at 690 V: a smaller drive is enough
    amps, issues = drive_amps("433")
    assert amps == "" and [(i["severity"], i["message"]) for i in issues] == [
        ("warning", "No drive is matched: 433 V is not 200-240, 380-415, 440-480, 550-600 or 660-690 V")]
    assert drive_amps("415")[1] == []
