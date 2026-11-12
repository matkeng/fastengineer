# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Motor Data: the WEG W22 range every project starts with, and matching a load to a motor."""

from __future__ import annotations

from collections import Counter

import pytest

from workbench_core.keylists.load_calcs import apply_calcs, check_calcs
from workbench_core.keylists.loadgen import LISTS, generate
from workbench_core.keylists.loadlist import LoadListRow
from workbench_core.keylists.motors import check_motors, default_motors, motor_for
from workbench_core.keylists.tag_paths import Links
from workbench_core.keylists.validate import check_load_types
from workbench_core.mel.load_fields import LoadCalc, LoadField, default_load_fields
from workbench_core.refdata import RefValidationError

W22 = default_motors()


def test_the_w22_tables_as_printed() -> None:
    # catalogue pages 24-27: 2 pole 33 + 5 High-Output, 4 pole 36 + 4, 6 pole 33 + 2, 8 pole 30 + 2
    assert Counter((m.poles, m.design) for m in W22) == {(2, "Standard"): 33, (2, "High-Output"): 5, (4, "Standard"): 36,
                                                         (4, "High-Output"): 4, (6, "Standard"): 33, (6, "High-Output"): 2,
                                                         (8, "Standard"): 30, (8, "High-Output"): 2}
    assert len({m.part_no for m in W22}) == len(W22) == 145 and len({m.id for m in W22}) == 145
    k25 = next(m for m in W22 if m.part_no == "K25 W22")  # 4 pole 7.5 kW, page 25
    assert (k25.kw, k25.frame, k25.speed, k25.flc, k25.il_ir, k25.torque, k25.tl_tr, k25.tb_tr) == (7.5, "132M", 1470, 13.5, 8.2, 48.7, 2.8, 3.7)
    assert (k25.eff50, k25.eff75, k25.eff100, k25.pf50, k25.pf75, k25.pf100) == (90.5, 91.4, 91.8, 0.65, 0.77, 0.84)
    assert (k25.sound, k25.inertia, k25.locked_cold, k25.locked_hot, k25.weight, k25.voltage, k25.frequency) == (56, 0.0642, 40, 18, 78, 415, 50)
    k20 = next(m for m in W22 if m.part_no == "K20/1 W22")  # 2 pole High-Output, 112M* on page 24
    assert (k20.design, k20.frame, k20.reduced_frame, k20.kw) == ("High-Output", "112M", True, 5.5)
    last = next(m for m in W22 if m.part_no == "K62B/1 W22")  # the last row of page 27
    assert (last.poles, last.kw, last.frame, last.weight) == (8, 132, "315L", 1500)


def test_a_load_gets_the_smallest_motor_that_fits() -> None:
    assert motor_for(7.5, "kW", 4, W22).part_no == "K25 W22"
    assert motor_for(8, "kW", 4, W22).part_no == "K28 W22"  # 9.2 kW: the next size up
    assert motor_for(10, "HP", 2, W22).part_no == "K24 W22"  # 7.46 kW -> 7.5 kW
    assert motor_for(5.5, "kW", 2, W22).part_no == "K20 W22"  # Standard before the High-Output K20/1
    assert motor_for(7.5, "Amps", 4, W22) is None and motor_for(7.5, "kW", "", W22) is None and motor_for(500, "kW", 4, W22) is None


def test_motor_rows_are_checked() -> None:
    ok = check_motors([{"part_no": "X1", "poles": "4", "kw": "11", "flc": "20.5", "design": "high output", "reduced_frame": "Yes"}])
    assert (ok[0].design, ok[0].reduced_frame, ok[0].flc) == ("High-Output", True, 20.5)
    with pytest.raises(RefValidationError) as exc:
        check_motors([{"id": "a", "part_no": "X1", "poles": "3", "kw": "0"}, {"id": "b", "part_no": "x1", "poles": "4", "kw": "5", "flc": "lots"}])
    assert set(exc.value.fields) == {"a.poles", "a.kw", "b.part_no", "b.flc"}


def _load(tag: str, kw, poles, units="kW") -> LoadListRow:
    return LoadListRow(recipe_id="m", key=tag, source="MEL", target="MEL", load_type_id="t1",
                       values={"tag": tag, "load_rating": kw, "load_units": units, "poles": poles})


def test_template_rows_and_calculations_reach_the_motor() -> None:
    types = check_load_types([{"id": "t1", "code": "DOL", "name": "DOL", "rating_unit": "kW", "voltage": "415", "phases": "AC-3-phase",
                               "rows": {"equipment_list": [{"Tag": "<<Tag>>", "Model": "<<Motor.PartNo>> <<Motor.Frame>>",
                                                            "Rating": "<<Motor.FLC>>", "Remarks": "<<Motor.Eff100|default:no motor>>"}]}}])
    loads = [_load("P-1", 7.5, 4), _load("P-2", 30, 2), _load("P-3", 7.5, "")]
    lt = {t.id: t for t in types.items}
    eq = generate("equipment_list", loads, lt, {}, links=Links(load_types=types.items, loads=loads, motors=W22))
    rows = {r.cells[0]: dict(zip(LISTS["equipment_list"].columns, r.cells)) for r in eq.rows}
    assert (rows["P-1"]["Model"], rows["P-1"]["Rating"], rows["P-1"]["Remarks"]) == ("K25 W22 132M", 13.5, 91.8)
    assert rows["P-2"]["Model"] == "K37 W22 200L" and rows["P-3"]["Remarks"] == "no motor"
    calc = LoadField(key="input_kw", label="Input kW", kind="calc",
                     calc=LoadCalc(formula="<<rating>> / <<Motor.Eff100>> * 100", applies_if="<<Motor.PartNo>> != ''", decimals=2))
    fields = default_load_fields().model_copy(update={"fields": [*default_load_fields().fields, calc]})
    check_calcs(fields)
    apply_calcs(loads, fields, lt, {}, motors=W22)
    assert [r.values["input_kw"] for r in loads] == [round(7.5 / 91.8 * 100, 2), round(30 / 94.2 * 100, 2), ""]
