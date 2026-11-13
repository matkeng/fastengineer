# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from workbench_core.mel.models import AutoBranch

from workbench_core.mel import (
    AutoColumn,
    ColumnRule,
    CustomRow,
    FieldMap,
    IngestError,
    Override,
    Recipe,
    Revision,
    RowRule,
    TextColumn,
    load_list,
    parse_csv,
    run_pipeline,
    unique_headers,
    unique_keys,
)

SAMPLES = Path(__file__).resolve().parents[2] / "samples"


def _rev(csv_text: str, key: str) -> Revision:
    original, headers, rows, warnings = parse_csv(csv_text.encode())
    unique_keys(rows, key)
    return Revision(id="r", rev=1, file_name="t.csv", source="csv", key_header=key,
                    num_rows=len(rows), num_cols=len(headers), uploaded_at=datetime.now(timezone.utc),
                    headers=headers, headers_original=original, rows=rows, warnings=warnings)


CSV = """Tag,Desc,HP,Type
P-1,Pump one,40,Pump
P-2,Pump two,10,Pump
F-1,Fan,5,Fan
"""


def _rows(result):
    return {r.key: r.values for r in result.rows}


def test_unique_headers_and_keys() -> None:
    assert unique_headers(["A", " A ", "", "", "B"]) == ["A", "A_1", "Blank", "Blank_1", "B"]
    rows = [{"k": "X"}, {"k": " X"}, {"k": ""}, {"k": "Y"}]
    assert unique_keys(rows, "k") == 2  # " X" and ""
    assert [r["k"] for r in rows] == ["X", "X_1", "Blank", "Y"]


def test_csv_parsing() -> None:
    _, headers, rows, warnings = parse_csv("a;b\n1;2\n\n3;4\n".encode("utf-8-sig"))
    assert headers == ["a", "b"] and len(rows) == 2 and not warnings
    _, _, rows, warnings = parse_csv("Tag,Desc\nP-1,Café\n".encode("cp1252"))
    assert rows[0]["Desc"] == "Café" and "Windows-1252" in warnings[0]
    with pytest.raises(IngestError):
        parse_csv(b"")


def test_full_pipeline_order() -> None:
    rev = _rev(CSV, "Tag")
    recipe = Recipe(
        id="x", name="MEL",
        columns=[ColumnRule(header="Type", visible=False), ColumnRule(header="HP", rename="Motor HP"),
                 ColumnRule(header="Tag", visible=False, rename="nope")],  # key can't be hidden/renamed
        hidden_rows=[RowRule(key="F-1")],
        text_columns=[TextColumn(name="Source", value="MEL")],
        overrides=[Override(key="P-2", column="Motor HP", value="15"),
                   Override(key="P-1", column="Source", value="Vendor")],  # override a text column
        custom_rows=[CustomRow(key="LC-1", values={"Desc": "Load centre", "Motor HP": "0"})],
        auto_columns=[
            AutoColumn(name="kW", statement="<<Motor HP>> > 0", true_val="round(<<Motor HP>> * 0.746, 2)",
                       false_val="0", error_val="?"),
            AutoColumn(name="Size", statement="<<kW>> >= 20", true_val="Large", false_val="Small"),
        ],
    )
    res = run_pipeline(rev, recipe)
    assert res.headers == ["Tag", "Desc", "Motor HP", "Source", "kW", "Size"]
    rows = _rows(res)
    assert set(rows) == {"P-1", "P-2", "LC-1"}  # F-1 hidden, custom row appended
    assert rows["P-2"]["Motor HP"] == "15" and rows["P-2"]["kW"] == "11.19"  # override before auto
    assert rows["P-1"]["Source"] == "Vendor" and rows["P-2"]["Source"] == "MEL"
    assert rows["P-1"]["kW"] == "29.84" and rows["P-1"]["Size"] == "Large"  # chained auto columns
    assert rows["LC-1"]["Source"] == "-" and rows["LC-1"]["kW"] == "0"  # custom rows get calcs
    assert next(r for r in res.rows if r.key == "P-2").overridden == ["Motor HP"]
    assert res.issues == []

    # Each editor sees the table before its own stage.
    assert run_pipeline(rev, recipe, "text").headers == ["Tag", "Desc", "Motor HP", "Source"]
    assert "Source" not in run_pipeline(rev, recipe, "rows").headers
    assert [r.key for r in run_pipeline(rev, recipe, "rows").hidden_rows] == ["F-1"]


def test_auto_column_values_cannot_inject() -> None:
    rev = _rev('Tag,Name\nA,"x"" or True or ""y"\nB,Pump\n', "Tag")
    recipe = Recipe(id="x", name="m", auto_columns=[
        AutoColumn(name="IsPump", statement="<<Name>> == 'Pump'", true_val="yes", false_val="no"),
        AutoColumn(name="Quoted", statement='"<<Name>>" == "Pump"', true_val="1", false_val="0"),
        AutoColumn(name="Bad", statement="<<Name>> +", error_val="ERR"),
    ])
    rows = _rows(run_pipeline(rev, recipe))
    assert rows["A"]["IsPump"] == "no" and rows["B"]["IsPump"] == "yes"
    assert rows["B"]["Quoted"] == "1"
    assert rows["A"]["Bad"] == "ERR"


def test_rule_health_after_revision() -> None:
    recipe = Recipe(
        id="x", name="m",
        columns=[ColumnRule(header="Gone", visible=False)],
        hidden_rows=[RowRule(key="Z-9")],
        overrides=[Override(key="P-1", column="Nope", value="1")],
        custom_rows=[CustomRow(key="P-1")],
        auto_columns=[AutoColumn(name="X", statement="<<Missing>> > 1")],
    )
    res = run_pipeline(_rev(CSV, "Tag"), recipe)
    kinds = sorted(i.kind for i in res.issues)
    assert kinds == ["auto", "columns", "custom", "overrides", "rows"]
    assert all(r.values["X"] == "ERROR" for r in res.rows)


def test_load_list_mapping() -> None:
    rev = _rev(CSV, "Tag")
    recipe = Recipe(id="x", name="m", mapping=[
        FieldMap(field="tag", column="Tag"), FieldMap(field="desc", column="Desc"),
        FieldMap(field="load_rating", column="HP"), FieldMap(field="load_units", manual="HP"),
        FieldMap(field="is_a_loadcentre", manual="no"), FieldMap(field="phases", column="Desc"),
    ])
    ll = load_list(run_pipeline(rev, recipe), recipe)
    assert ll.fields == ["tag", "desc", "load_units", "load_rating", "phases", "is_a_loadcentre"]
    assert ll.rows[0] == {"tag": "P-1", "desc": "Pump one", "load_units": "HP", "load_rating": 40,
                          "phases": "Pump one", "is_a_loadcentre": False}
    assert "non-numeric 'phases'" in ll.warnings[0]


@pytest.mark.skipif(not (SAMPLES / "mel-sample.csv").exists(), reason="samples missing")
def test_samples_reapply_recipe() -> None:
    def rev(name: str) -> Revision:
        return _rev((SAMPLES / name).read_text(), "Equipment Tag")

    r1 = rev("mel-sample.csv")
    assert r1.headers[-3:] == ["Notes", "Notes_1", "Blank"]
    assert [r["Equipment Tag"] for r in r1.rows][-2:] == ["P-102_1", "Blank"]
    recipe = Recipe(id="x", name="MEL",
                    columns=[ColumnRule(header="Notes_1", visible=False), ColumnRule(header="Blank", visible=False)],
                    hidden_rows=[RowRule(key="P-102_1"), RowRule(key="Blank")],
                    overrides=[Override(key="F-301", column="Motor HP", value="7.5")])
    assert len(run_pipeline(r1, recipe).rows) == 6 and not run_pipeline(r1, recipe).issues
    # Rev 2: F-301 removed, Notes columns gone -> the recipe still applies, issues are reported.
    res2 = run_pipeline(rev("mel-sample-rev2.csv"), recipe)
    assert len(res2.rows) == 6
    assert {i.kind for i in res2.issues} == {"columns", "rows", "overrides"}


def test_auto_column_cascades_else_ifs_with_not() -> None:
    rev = _rev("Tag,Kind,kW\nP-1,Pump,90\nP-2,Pump,15\nF-1,Fan,3\nV-1,Valve,\nX-1,Spare,abc\n", "Tag")
    size = AutoColumn(name="Size", statement="<<Kind>> == 'Valve'", true_val="Valve",  # first: comparing a blank kW with a number is an error
                      else_ifs=[AutoBranch(statement="<<kW>> >= 75", value="Large"),
                                AutoBranch(statement="<<kW>> >= 10", value="Medium"),
                                AutoBranch(statement="<<kW>> == ''", negate=True, value="Small")],
                      false_val="None", error_val="?")
    not_pump = AutoColumn(name="Not a pump", statement="<<Kind>> == 'Pump'", negate=True, true_val="Yes", false_val="No")
    rows = _rows(run_pipeline(rev, Recipe(id="x", name="m", auto_columns=[size, not_pump])))
    # the first condition that holds gives the value; NOT turns a condition round
    assert {k: r["Size"] for k, r in rows.items()} == {"P-1": "Large", "P-2": "Medium", "F-1": "Small", "V-1": "Valve", "X-1": "?"}
    assert {k: r["Not a pump"] for k, r in rows.items()} == {"P-1": "No", "P-2": "No", "F-1": "Yes", "V-1": "Yes", "X-1": "Yes"}
    # X-1: 'abc' >= 75 can't be worked out, so the row gets the error value
    # a column an Else if refers to that isn't there is reported, and every row gets the error value
    gone = AutoColumn(name="G", statement="True", else_ifs=[AutoBranch(statement="<<Nope>> > 1", value="x")], error_val="E")
    res = run_pipeline(rev, Recipe(id="x", name="m", auto_columns=[gone]))
    assert "Nope" in res.issues[0].message and {r.values["G"] for r in res.rows} == {"E"}
    # a recipe saved before Else if and NOT still reads
    old = AutoColumn.model_validate({"name": "Y", "statement": "True", "true_val": "1", "false_val": "0", "error_val": "E"})
    assert (old.negate, old.else_ifs) == (False, [])


def test_auto_column_condition_and_value_read_different_columns() -> None:
    # The If reads one column and the Then another: each must see its own column's value.
    rev = _rev("Tag,Kind,Rating\nP-1,Pump,7.5\nF-1,Fan,3\n", "Tag")
    col = AutoColumn(name="Pump kW", statement="<<Kind>> == 'Pump'", true_val="<<Rating>> * 2", false_val="<<Kind>>")
    rows = _rows(run_pipeline(rev, Recipe(id="x", name="m", auto_columns=[col])))
    assert (rows["P-1"]["Pump kW"], rows["F-1"]["Pump kW"]) == ("15", "Fan")


def test_find_replace_columns() -> None:
    from workbench_core.mel import FindReplace, Replacement

    recipe = Recipe(id="x", name="x", custom_rows=[CustomRow(key="C-1", values={"Type": "Pump"})],
                    find_replace=[
                        FindReplace(name="Kind", column="Type", replacements=[Replacement(find="Pump", replace="Centrifugal Pump"),
                                                                              Replacement(find="Fan", replace=""),
                                                                              Replacement(find="Gone", replace="X")]),
                        FindReplace(name="Kind 2", column="Kind", replacements=[Replacement(find="Centrifugal Pump", replace="CP")]),
                        FindReplace(name="Tag", column="Type"),  # name taken
                        FindReplace(name="Other", column="Nope"),  # no such column
                    ],
                    auto_columns=[AutoColumn(name="Calc", statement="<<Kind>> == ''", true_val="blank", false_val="<<Kind 2>>")])
    result = run_pipeline(_rev(CSV, "Tag"), recipe)
    rows = _rows(result)
    assert (rows["P-1"]["Kind"], rows["F-1"]["Kind"], rows["C-1"]["Kind"]) == ("Centrifugal Pump", "", "Centrifugal Pump")
    assert rows["P-1"]["Type"] == "Pump"  # the source column is untouched
    assert (rows["P-1"]["Kind 2"], rows["F-1"]["Kind 2"]) == ("CP", "")  # a later one can use an earlier one
    assert (rows["F-1"]["Calc"], rows["P-2"]["Calc"]) == ("blank", "CP")  # calculated columns see them
    assert [(i.kind, i.rule) for i in result.issues] == [("replace", "Tag"), ("replace", "Other")]
    assert "Kind" not in run_pipeline(_rev(CSV, "Tag"), recipe, upto="custom").headers
    # a whole value only: "Pump one" is not touched by a "Pump" rule
    r2 = Recipe(id="y", name="y", find_replace=[FindReplace(name="D", column="Desc", replacements=[Replacement(find="Pump", replace="Z")])])
    assert _rows(run_pipeline(_rev(CSV, "Tag"), r2))["P-1"]["D"] == "Pump one"
