# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Calculated fields of the Project Master Load List (keylists.load_calcs)."""

from __future__ import annotations

import pytest

from workbench_core.keylists.load_calcs import apply_calcs, check_calcs, order, refs
from workbench_core.keylists.loadlist import LoadListRow
from workbench_core.keylists.models import LoadType
from workbench_core.mel.load_fields import CalcCheck, LoadCalc, LoadField, LoadFields, default_load_fields
from workbench_core.refdata import RefValidationError

TYPES = {"t1": LoadType(id="t1", code="DOL", name="Direct on line", rating_unit="kW", voltage=415, phases="AC-3-phase")}
AREAS = {"a1": ("100", "Feed area")}


def _row(key: str, **values) -> LoadListRow:
    return LoadListRow(recipe_id="m", key=key, source="MEL", target="MEL", values={"tag": key} | values,
                       plant_area_id="a1", load_type_id="t1", cable_length=120.0, cable_size="16")


def _calc(key: str, label: str, formula: str, **more) -> LoadField:
    return LoadField(key=key, label=label, kind="calc", calc=LoadCalc(formula=formula, **more))


def _fields(*extra: LoadField) -> LoadFields:
    base = default_load_fields().fields + [LoadField(key="pf", label="Power factor", kind="number"),
                                           LoadField(key="eff", label="Efficiency", kind="number")]
    return LoadFields(fields=base + list(extra))


POWER = (
    _calc("kw", "Active power (kW)", "<<load_rating>> * 0.746 / <<eff>> if <<units>> == 'HP' else <<load_rating>> / <<eff>>", decimals=2,
          applies_if="<<load_rating>> != ''"),
    _calc("kva", "Apparent power (kVA)", "<<kw>> / <<pf>>", decimals=2,
          checks=[CalcCheck(rule="<<value>> < 1000", message="Over 1 MVA: check the rating", severity="warning")]),
    _calc("kvar", "Reactive power (kvar)", "sqrt(<<kva>>**2 - <<kw>>**2)", decimals=2),
    _calc("amps", "Rated current (A)", "<<kva>> * 1000 / (sqrt(3) * <<voltage>>)", decimals=1,
          checks=[CalcCheck(rule="<<value>> > 0", message="The current must be more than 0")]),
    _calc("kwh", "Annual consumption (kWh)", "<<kw>> * (<<utility>> or 1) * 8760", decimals=0),
)


def test_power_calculations_in_dependency_order() -> None:
    utility = LoadField(key="utility", label="Utility factor", kind="number")
    fields = _fields(utility, *reversed(POWER))  # listed out of order: worked out in the order they use each other
    check_calcs(fields)
    done = order(fields)
    assert done.index("kw") < done.index("kva") < done.index("kvar") and done.index("kva") < done.index("amps")
    rows = [_row("P-1", load_rating=30, load_units="HP", pf=0.85, eff=0.9, utility=0.5),
            _row("P-2", load_rating=11, pf=0.8, eff=1),  # units from the load type (kW), voltage 415 from it too
            _row("P-3", load_rating="", pf=0.8, eff=1)]
    apply_calcs(rows, fields, TYPES, AREAS)
    p1, p2, p3 = (r.values for r in rows)
    assert p1["kw"] == 24.87 and p1["kva"] == 29.26 and p1["kwh"] == round(24.87 * 0.5 * 8760)
    assert p2["kw"] == 11 and p2["kva"] == 13.75 and p2["kvar"] == 8.25 and p2["amps"] == 19.1
    assert p2["kwh"] == 96360 and rows[1].calc_issues == []
    # P-3 has no rating: Active power doesn't apply, so it is blank; dividing a blank can't be worked out
    # (a blank times a number stays blank, so the consumption is blank too)
    assert p3["kw"] == "" and p3["kwh"] == ""
    assert {i["field"] for i in rows[2].calc_issues} == {"kva", "kvar", "amps"}
    assert all("blank or text where a number is needed" in i["message"] for i in rows[2].calc_issues if i["field"] == "kva")


def test_checks_otherwise_and_errors() -> None:
    fields = _fields(_calc("kva", "kVA", "<<load_rating>> / <<pf>>", decimals=1, applies_if="<<loadtype>> == 'DOL'", otherwise="'n/a'",
                           checks=[CalcCheck(rule="<<value>> < 10", message="Too big", severity="warning"),
                                   CalcCheck(rule="<<value>> > <<load_rating>>")]))
    rows = [_row("A", load_rating=7.5, pf=0.8), _row("B", load_rating=20, pf=0.8), _row("C", load_rating=5, pf=0),
            _row("D", load_rating=5, pf=1), _row("E", load_rating=5, pf=1)]
    rows[4].load_type_id = None
    apply_calcs(rows, fields, TYPES, AREAS)
    assert [r.values["kva"] for r in rows] == [9.4, 25.0, "", 5.0, "n/a"]
    assert rows[0].calc_issues == []
    assert rows[1].calc_issues == [{"field": "kva", "severity": "warning", "message": "Too big"}]
    assert rows[2].calc_issues[0]["message"] == "Can't be worked out: division by zero"
    assert rows[3].calc_issues == [{"field": "kva", "severity": "error", "message": "Fails the check <<value>> > <<load_rating>>"}]
    assert rows[4].calc_issues == []  # doesn't apply: not checked


def test_what_is_refused() -> None:
    def refused(*calcs: LoadField) -> dict:
        with pytest.raises(RefValidationError) as exc:
            check_calcs(_fields(*calcs))
        return exc.value.fields

    n = len(_fields().fields)
    assert "not a field" in refused(_calc("a", "A", "<<nope>> * 2"))[f"{n}.formula"]
    assert "not an allowed function" in refused(_calc("a", "A", "open('x')"))[f"{n}.formula"]
    assert "its own answer" in refused(_calc("a", "A", "<<a>> + 1"))[f"{n}.formula"]
    assert "not a field" in refused(_calc("a", "A", "1", checks=[CalcCheck(rule="<<valu>> > 0")]))[f"{n}.checks.0"]
    assert "loop: A, B" in refused(_calc("a", "A", "<<b>> + 1"), _calc("b", "B", "<<a>> + 1"))["fields"]
    check_calcs(_fields(_calc("a", "A", "<<cable_length>> * <<rating>>", checks=[CalcCheck(rule="<<value>> >= 0")])))
    assert refs("<<A>> + << b >> + '<<A>>'") == ["a", "b"]
