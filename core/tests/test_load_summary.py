# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""The Load List Summary Page (keylists.load_summary)."""

from __future__ import annotations

import pytest

from workbench_core.keylists.load_calcs import APP_REFS, supply_chain
from workbench_core.keylists.load_summary import SummaryPage, check_page, work_out
from workbench_core.keylists.loadlist import LoadListRow
from workbench_core.refdata import RefValidationError


def _load(tag: str, kw=None, fed="", **more) -> LoadListRow:
    more.setdefault("supplied_from", f"m/{fed}" if fed else None)
    return LoadListRow(recipe_id="m", key=tag, source="MEL", target="MEL",
                       values={"tag": tag, "load_rating": kw} | more.pop("values", {}), **more)


LOADS = [_load("TX-1", 1000, "MSB", is_panel=True), _load("MSB", None, is_panel=True, supplied_from="primary"),
         _load("MCC-1", None, "TX-1", is_panel=True), _load("MCC-2", None, "TX-1", is_panel=True),
         _load("P-1", 75, "MCC-1"), _load("P-2", 30, "MCC-1", values={"standby": "Yes"}), _load("F-1", 11, "MCC-2"),
         _load("H-1", 9, "MSB"), _load("X-1", 5, "MCC-1", status="deleted")]
NAMES = {"tag", "load_rating", "standby", "supplychain", "loadtype", "ispanel"} | {r for r, _ in APP_REFS}

PAGE = {"tables": [{"name": "Transformer loading", "filter": "not <<ispanel>>", "rows": [
    {"name": "TX-1", "condition": "'TX-1' in <<supplychain>>", "ref_tag": "TX-1"},
    {"name": "MCC-1 only", "condition": "<<suppliedfrom>> == 'MCC-1'"},
    {"name": "Nothing", "condition": "<<tag>> == 'none'"}], "columns": [
    {"name": "Total kW", "func": "sum", "field": "load_rating"},
    {"name": "Duty kW", "func": "sum", "field": "load rating", "condition": "<<standby>> != 'Yes'"},
    {"name": "Loads", "func": "count"},
    {"name": "Largest", "func": "max", "field": "load_rating"},
    {"name": "Average kW", "func": "average", "field": "load_rating", "decimals": 1},
    {"name": "Loading %", "kind": "formula", "formula": "<<Duty kW>> / <<Ref.Load Rating>> * 100", "applies_if": "<<Ref.load_rating>> != ''",
     "otherwise": "'-'", "decimals": 1, "checks": [{"rule": "<<value>> < 80", "message": "Over 80 %", "severity": "warning"}]},
    {"name": "Spare kW", "kind": "formula", "formula": "<<ref.load_rating>> - <<Duty kW>> if <<Loading %>> != '-' else ''"}]}]}


def test_supply_chain() -> None:
    by_ref = {r.ref(): r for r in LOADS}
    assert supply_chain(LOADS[4], by_ref) == ["MCC-1", "TX-1", "MSB", "Primary Supply"]


def test_a_transformers_loading() -> None:
    with pytest.raises(RefValidationError) as exc:  # "Loads" is a row's own name
        check_page(SummaryPage.model_validate(PAGE), NAMES)
    assert "taken" in exc.value.fields["0.columns.2.name"]
    page = PAGE | {"tables": [PAGE["tables"][0] | {"columns": [c | ({"name": "Count"} if c["name"] == "Loads" else {})
                                                                for c in PAGE["tables"][0]["columns"]]}]}
    page = check_page(SummaryPage.model_validate(page), NAMES)
    (t,) = work_out(page, LOADS, {}, {})
    assert t.columns == ["Total kW", "Duty kW", "Count", "Largest", "Average kW", "Loading %", "Spare kW"]
    rows = {r.name: r for r in t.rows}
    assert rows["TX-1"].cells == [116, 86, 3, 75, 38.7, 8.6, 914] and rows["TX-1"].tags == ["P-1", "P-2", "F-1"]
    assert rows["MCC-1 only"].cells == [105, 75, 2, 75, 52.5, "-", ""]  # no reference load: Otherwise
    assert rows["Nothing"].cells == ["", "", 0, "", "", "-", ""] and rows["Nothing"].loads == 0
    assert rows["Total"].total and rows["Total"].cells[:3] == [125, 95, 4]  # every load the filter lets in (not the deleted one)
    assert rows["TX-1"].issues == []


def test_checks_and_problems() -> None:
    page = {"tables": [{"name": "T", "rows": [{"name": "All", "ref_tag": "TX-1"}, {"name": "Gone", "ref_tag": "NOPE"}], "total_row": False,
                        "columns": [{"name": "kW", "func": "sum", "field": "load_rating"},
                                    {"name": "Pct", "kind": "formula", "formula": "<<kW>> / <<Ref.load_rating>> * 100",
                                     "checks": [{"rule": "<<value>> < 50", "message": "Too loaded"}]}]}]}
    (t,) = work_out(check_page(SummaryPage.model_validate(page), NAMES), LOADS, {}, {})
    assert [(i.severity, i.message) for i in t.rows[0].issues] == [("error", "Too loaded")]  # 1135 kW of 1000
    assert "No active load is tagged NOPE" in t.rows[1].issues[-1].message
    assert t.rows[1].issues[0].message.startswith("Can't be worked out")


@pytest.mark.parametrize("change, field, message", [
    ({"name": ""}, "0.name", "needs a name"),
    ({"filter": "<<nope>> > 1"}, "0.filter", "not something it can use: <<nope>>"),
    ({"columns": [{"name": "A", "field": "nope"}]}, "0.columns.0.field", "not a field"),
    ({"columns": [{"name": "A", "kind": "formula", "formula": "<<B>>"}, {"name": "B", "kind": "formula", "formula": "<<A>>"}]}, "0.columns",
     "loop"),
    ({"columns": [{"name": "A", "kind": "formula", "formula": "<<load_rating>>"}]}, "0.columns.0.formula", "not something it can use"),
    ({"rows": [{"name": "R", "condition": "open('x')"}]}, "0.rows.0.condition", "not an allowed function"),
])
def test_what_is_refused(change, field, message) -> None:
    with pytest.raises(RefValidationError) as exc:
        check_page(SummaryPage.model_validate({"tables": [{"name": "T"} | change]}), NAMES)
    assert message in exc.value.fields[field]
