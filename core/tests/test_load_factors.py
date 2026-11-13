# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Load Factors: the typical factors by equipment type, matched on a load's Equipment type."""

from __future__ import annotations

import pytest

from workbench_core.keylists import workbooks as wbk
from workbench_core.keylists.load_calcs import apply_calcs, check_calcs
from workbench_core.keylists.load_factors import check_load_factors, default_load_factors, load_factor_fields, load_factor_for
from workbench_core.keylists.loadgen import LISTS, generate
from workbench_core.keylists.loadlist import LoadListRow
from workbench_core.keylists.tag_paths import Links
from workbench_core.keylists.validate import check_load_types
from workbench_core.mel.load_fields import LoadCalc, LoadField, default_load_fields
from workbench_core.refdata import RefValidationError

LF = default_load_factors()


def _row(name: str):
    return next(r for r in LF if r.equipment_type == name)


def test_the_typical_factors() -> None:
    assert len(LF) == 31 and LF[0].equipment_type == "Default" and LF[-1].equipment_type == "Distributor"
    assert all((r.nameplate_lf, r.optimised_lf) == (0.75, 0.95) for r in LF)
    assert (_row("Crane/Hoist").avg_demand, _row("Crane/Hoist").max_demand) == (0.05, 0.5)
    assert _row("Boiler").avg_demand == 0.25 and _row("Carbon Regen Kiln").avg_demand == 0.83 and _row("Ball Charger").avg_demand == 0.1
    assert _row("Compressor").avg_demand == _row("Air Conditioner").avg_demand == 0.5 and _row("Davit").avg_demand == 0.05


def test_a_load_matches_its_equipment_type_or_the_default() -> None:
    row, matched = load_factor_for("  crane/HOIST ", LF)
    assert row.equipment_type == "Crane/Hoist" and matched
    row, matched = load_factor_for("Belt Conveyor", LF)
    assert row.equipment_type == "Default" and not matched
    assert load_factor_for("", LF)[0].equipment_type == "Default"
    assert load_factor_for("Pump", [r for r in LF if r.equipment_type != "Default"]) == (None, False)
    f = load_factor_fields(_row("Boiler"))
    assert (f["equipmenttype"], f["nameplatelf"], f["avgdemand"], f["matched"]) == ("Boiler", 0.75, 0.25, True)
    assert set(load_factor_fields(None).values()) == {""}


def test_rows_are_checked() -> None:
    ok = check_load_factors([{"equipment_type": " Pump  Station ", "avg_demand": "0.8", "max_demand": ""}])
    assert (ok[0].equipment_type, ok[0].avg_demand, ok[0].max_demand) == ("Pump Station", 0.8, None)
    with pytest.raises(RefValidationError) as exc:
        check_load_factors([{"id": "a", "equipment_type": ""}, {"id": "b", "equipment_type": "Pump", "nameplate_lf": "x"},
                            {"id": "c", "equipment_type": "pump", "max_demand": "11"}])
    assert set(exc.value.fields) == {"a.equipment_type", "b.nameplate_lf", "c.equipment_type", "c.max_demand"}


def test_the_workbook_round_trip() -> None:
    sheets = wbk.export_load_factors(LF)
    as_read = {t.casefold(): [{str(h).casefold(): ("" if v is None else str(v)) for h, v in zip(rows[0], r)} for r in rows[1:]]
               for t, rows in sheets}
    assert check_load_factors(wbk.import_load_factors(as_read, LF).payload["items"]) == LF


def test_template_rows_and_calculations_reach_the_factors() -> None:
    types = check_load_types([{"id": "t1", "code": "DOL", "name": "DOL", "rating_unit": "kW", "voltage": "415", "phases": "AC-3-phase",
                               "rows": {"equipment_list": [{"Tag": "<<Tag>>", "Remarks": "<<LoadFactor.EquipmentType>> <<LoadFactor.AvgDemand>>"}]}}])
    loads = [LoadListRow(recipe_id="m", key=k, source="MEL", target="MEL", load_type_id="t1",
                         values={"tag": k, "load_rating": 10, "load_units": "kW", "equip_type": t})
             for k, t in (("H-1", "crane/hoist"), ("X-1", "Mystery"))]
    lt = {t.id: t for t in types.items}
    eq = generate("equipment_list", loads, lt, {}, links=Links(load_types=types.items, loads=loads, load_factors=LF))
    rows = {r.cells[0]: dict(zip(LISTS["equipment_list"].columns, r.cells)) for r in eq.rows}
    assert rows["H-1"]["Remarks"] == "Crane/Hoist 0.05" and rows["X-1"]["Remarks"] == "Default 1"
    calc = LoadField(key="avg_kw", label="Avg kW", kind="calc",
                     calc=LoadCalc(formula="<<rating>> * <<LoadFactor.NameplateLF>> * <<LoadFactor.AvgDemand>>", decimals=3))
    fields = default_load_fields().model_copy(update={"fields": [*default_load_fields().fields, calc]})
    check_calcs(fields)
    apply_calcs(loads, fields, lt, {}, load_factors=LF)
    assert (loads[0].values["avg_kw"], loads[1].values["avg_kw"]) == (round(10 * 0.75 * 0.05, 3), 7.5)
