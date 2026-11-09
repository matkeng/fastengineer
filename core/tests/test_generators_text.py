# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
from datetime import date, datetime

import pytest

from workbench_core.generators.expr import ExprError, evaluate, parses
from workbench_core.generators.text import as_typed, collapse_spaces, is_truthy, replace_ci, to_text


@pytest.mark.parametrize("value,text", [
    (None, ""), ("#N/A", ""), ("#VALUE!", ""),
    (42, "42"), (42.0, "42"), (2.5, "2.5"), (117.3, "117.3"), (0.1 + 0.2, "0.3"), (-4.0, "-4"),
    (1 / 3, "0.333333333333333"), (1e-5, "1E-05"), (1.5e20, "1.5E+20"),
    (True, "True"), (False, "False"),
    (date(2026, 3, 7), "07/03/2026"), (datetime(2026, 3, 7), "07/03/2026"),
    ("  spaced ", "  spaced "),  # text unchanged, no trimming
])
def test_value_to_text(value, text):
    assert to_text(value) == text


def test_replace_case_insensitive_and_literal():
    assert replace_ci("<<QTY>> x <<qty>>", "<<Qty>>", "5") == "5 x 5"
    assert replace_ci("a.b", ".", "$1") == "a$1b"  # literal, not regex
    assert replace_ci("<<LEN2>>", "<<LEN>>", "70") == "<<LEN2>>"  # prefix keys do not clash


def test_collapse_spaces_three_passes_vs_full():
    s = "A" + " " * 10 + "B"
    assert collapse_spaces("A  B   C") == "A B C"
    assert collapse_spaces(s) == "A  B"  # compat: 10 -> 5 -> 3 -> 2 (Appendix D item 7)
    assert collapse_spaces(s, full=True) == "A B"


@pytest.mark.parametrize("text,value", [
    ("75", 75), ("2.5", 2.5), ("-3", -3), ("1e3", 1000), ("TRUE", True), ("false", False),
    ("07/03/2026", date(2026, 3, 7)), ("100-LB01", "100-LB01"), ("", None), ("31/02/2026", "31/02/2026"),
])
def test_as_typed(text, value):
    v = as_typed(text)
    assert v == value and type(v) is type(value)


def test_literal_protection():
    assert as_typed("35", from_literal=True, literal_value="35") == "35"


def test_truthy():
    assert all(is_truthy(v) for v in (True, "TRUE", "yes", "Y", "1", 1, "x", "Locked"))
    assert not any(is_truthy(v) for v in (False, None, "", "no", 0, "2"))


@pytest.mark.parametrize("src,value", [
    ('="100LB01AB3-P2 to P"& 5+1', "100LB01AB3-P2 to P6"),
    ("=15*5", 75), ("=15*(5-1)", 60), ("=-2^2", 4), ("=2-3^2", -7), ("=2*3+4", 10), ("=7/2", 3.5),
    ('="A" & 1.5', "A1.5"), ('=1&2+3', "15"), ('=IF(1>2,"y","n")', "n"), ("=ROUND(2.5,0)", 3), ("=ROUND(-2.5,0)", -3),
    ("=CEILING(7,5)", 10), ("=MAX(1,9,3)", 9), ("=MIN(4,2)", 2), ('=LEN("abc")', 3), ('=UPPER("ab")', "AB"),
    ('="say ""hi"""', 'say "hi"'), ("=TRUE", True), ('="5"*2', 10),
])
def test_expressions(src, value):
    assert evaluate(src) == value


@pytest.mark.parametrize("src", ["=<<No Value Found>>*5", "=1+", '="abc"*2', "=FOO(1)", "=(1", "=1/0"])
def test_expression_errors(src):
    with pytest.raises(ExprError):
        evaluate(src)
    assert not parses(src) or src in ('="abc"*2', "=1/0")


def test_expression_column_refs():
    assert evaluate("=[Qty]*[Len]", refs=lambda c: {"Qty": 5, "Len": "15"}[c]) == 75
