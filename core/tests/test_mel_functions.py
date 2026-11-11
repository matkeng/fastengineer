# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
from datetime import datetime, timezone

import re

import pytest

from workbench_core.mel import AutoColumn, Recipe, run_pipeline
from workbench_core.mel.functions import FUNCTION_HELP, REMOVED, SAMPLE_ROW, make_interpreter
from workbench_core.mel.models import Revision

EXAMPLES = [(group, expr, result) for group, _about, items in FUNCTION_HELP for expr, result, _what in items]


def _row_result(expr: str) -> tuple[str, bool]:
    """What a calculated column with this expression as its value writes for SAMPLE_ROW."""
    headers = list(SAMPLE_ROW)
    rev = Revision(id="r", rev=1, file_name="t.csv", source="csv", key_header="Tag", num_rows=1, num_cols=len(headers),
                   uploaded_at=datetime.now(timezone.utc), headers=headers, headers_original=headers, rows=[dict(SAMPLE_ROW)])
    col = AutoColumn(name="Out", statement="True", true_val=expr, error_val="ERROR")
    row = run_pipeline(rev, Recipe(id="x", name="m", auto_columns=[col])).rows[0]
    return row.values["Out"], "Out" in row.auto_errors


@pytest.mark.parametrize("group,expr,result", EXAMPLES, ids=[e[1] for e in EXAMPLES])
def test_every_help_example_gives_what_the_help_says(group: str, expr: str, result: str) -> None:
    got, error = _row_result(expr)
    assert (got, error) == (result, False), f"{group}: {expr}"


@pytest.mark.parametrize("group,expr,result", [e for e in EXAMPLES if e[0] == "Comparisons and logic"],
                         ids=[e[1] for e in EXAMPLES if e[0] == "Comparisons and logic"])
def test_the_conditions_work_as_conditions(group: str, expr: str, result: str) -> None:
    if result not in ("TRUE", "FALSE"):
        return
    headers = list(SAMPLE_ROW)
    rev = Revision(id="r", rev=1, file_name="t.csv", source="csv", key_header="Tag", num_rows=1, num_cols=len(headers),
                   uploaded_at=datetime.now(timezone.utc), headers=headers, headers_original=headers, rows=[dict(SAMPLE_ROW)])
    col = AutoColumn(name="Out", statement=expr, true_val="yes", false_val="no")
    assert run_pipeline(rev, Recipe(id="x", name="m", auto_columns=[col])).rows[0].values["Out"] == ("yes" if result == "TRUE" else "no")


def test_a_calculated_column_cannot_reach_outside_the_row(tmp_path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("password")
    for name in REMOVED:
        assert name not in make_interpreter().symtable
    got, error = _row_result(f"open({str(secret)!r}).read()")
    assert "password" not in got  # open is unknown: the text is taken as plain text, nothing is read
    got, error = _row_result(f"open({str(secret)!r}).read() + <<Tag>>")
    assert (got, error) == ("ERROR", True)


def test_the_help_names_everything_that_is_allowed() -> None:
    from workbench_core.mel.functions import FUNCTIONS, METHODS, NAMES
    text = " ".join(f"{e} {w}" for _g, _a, items in FUNCTION_HELP for e, _r, w in items)
    for name in [*FUNCTIONS, *METHODS, *(n for n in NAMES if n != "None")]:
        assert re.search(rf"\b{name}\b", text), f"{name} is allowed but not in the help"


ALLOWED = ["<<kW>> * 2", "round(<<kW>>, 1)", "<<Tag>>.split('-')[0]", "<<Tag>>[-2:]", "'%.1f kW' % <<kW>>", "<<Type>> in ('DOL', 'VSD')",
           "'big' if <<kW>> > 50 else 'small'", "not <<Tag>>", "min(<<kW>>, 5, 9)", "<<Tag>>.zfill(10)", "-<<kW>>", "pi * e"]
REFUSED = {
    "open('/etc/passwd').read()": "'open' is not an allowed function",
    "<<Tag>>.read()": "'.read()' is not an allowed text function",
    "open('/etc/passwd')": "'open' is not an allowed function",
    "__import__('os')": "'__import__' is not an allowed function",
    "<<Tag>>.__class__": "'.__class__' is not allowed",
    "<<Tag>>.format(1)": "'.format()' is not an allowed text function",
    "[x for x in <<Tag>>]": "loops can't be written",
    "lambda: 1": "loops can't be written",
    "isinstance(<<kW>>, int)": "'isinstance' is not an allowed function",
    "sum([1, 2])": "'sum' is not an allowed function",
    "round(<<kW>>, ndigits=1)": "without names",
    "f'{<<kW>>}'": "f-strings are not allowed",
    "{'a': 1}": "{ } is not allowed",
    "<<Tag>>[<<kW>>]": "a position in [ ] is a whole number",
    "<<Tag>>.zfill(10 ** 9)": "takes a width from 0 to 1000",
    "<<Tag>>.zfill(5000)": "takes a width from 0 to 1000",
    "x": "'x' is not allowed",
    "round": "round is a function",
    "1 + ": "can't be read",
    "1 & 2": "that operator is not allowed",
    "1 is 1": "that comparison is not allowed",
    "'" + "a" * 600 + "'": "at most 500 characters",
    "1" + " + 1" * 400: "at most 1000 characters",
}


@pytest.mark.parametrize("expr", ALLOWED)
def test_allowed_expressions_run(expr: str) -> None:
    got, error = _row_result(expr)
    assert not error, (expr, got)


@pytest.mark.parametrize("expr,why", REFUSED.items(), ids=[k[:40] for k in REFUSED])
def test_anything_else_is_refused_with_the_reason(expr: str, why: str) -> None:
    from workbench_core.mel.pipeline import _Expr
    e = _Expr(expr)
    assert e.problem and why in e.problem, (expr, e.problem)
    headers = list(SAMPLE_ROW)
    rev = Revision(id="r", rev=1, file_name="t.csv", source="csv", key_header="Tag", num_rows=1, num_cols=len(headers),
                   uploaded_at=datetime.now(timezone.utc), headers=headers, headers_original=headers, rows=[dict(SAMPLE_ROW)])
    res = run_pipeline(rev, Recipe(id="x", name="m", auto_columns=[AutoColumn(name="Out", statement=expr, true_val="y", error_val="E")]))
    assert res.rows[0].values["Out"] == "E" and "Not allowed" in res.issues[0].message and "If: " in res.issues[0].message


def test_what_a_guard_stops_at_run_time() -> None:
    # a format or a padding taken from a cell is checked when it runs
    for expr in ("<<Tag>> % 1", "'%999999999d' % 1", "<<Desc>>.replace('', <<Desc>> * 9000)", "<<kW>>.upper()"):
        got, error = _row_result(expr)
        assert (got, error) == ("ERROR", True), expr
    assert _row_result("10 ** 100000") == ("ERROR", True)  # the evaluator caps powers
    assert _row_result("'a' * 10 ** 6") == ("ERROR", True)  # and repeated text


def test_plain_text_in_a_value_is_never_run() -> None:
    for text in ("Motor", "Pump station", "open('x').read()", "sum([1, 2])"):
        assert _row_result(text) == (text, False)
