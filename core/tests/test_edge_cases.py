# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Edge cases that used to give a wrong answer or an error."""

from __future__ import annotations

import io

import numpy as np
import pytest
from openpyxl import load_workbook

from workbench_core.generators.xlsx_import import _ROW_OF_REF
from workbench_core.keylists.load_summary import _aggregate, _number
from workbench_core.keylists.units import rating_kw, unit_kind
from workbench_core.mel.export import _num, _put
from workbench_core.symbols.match import masked_ncc


def test_units_are_read_one_way() -> None:
    assert [unit_kind(u) for u in ("", None, "kW", " KW ", "hp", "HP", "A", "amp", "Amps")] == [
        "kW", "kW", "kW", "kW", "HP", "HP", "Amps", "Amps", "Amps"]
    assert unit_kind("kVA") == "kVA" and unit_kind("W") is None
    assert rating_kw(10, "kW") == 10 and rating_kw(10, "hp") == pytest.approx(7.457)
    assert rating_kw(10, "A") is None and rating_kw(10, "kVA") is None


def test_an_empty_mask_matches_nothing() -> None:
    page = np.zeros((40, 40), np.float32)
    symbol = np.full((10, 10), 255, np.uint8)
    assert masked_ncc(page, symbol, np.zeros((10, 10), np.uint8)) is None  # was a ZeroDivisionError


def test_a_formulas_row_numbers_not_its_function_names() -> None:
    row = lambda f: _ROW_OF_REF.sub(r"\1{row}", f)
    assert row("=A5&\"-\"&$B5") == "=A{row}&\"-\"&$B{row}"
    assert row("=LOG10(C12)+ATAN2(D12,E12)") == "=LOG10(C{row})+ATAN2(D{row},E{row})"
    assert row("=A$5") == "=A$5"  # a fixed row stays fixed


def test_summary_numbers() -> None:
    assert _number("1,000") == 1000 and _number(" 2.5 ") == 2.5
    assert _number("nan") is None and _number(float("inf")) is None and _number("x") is None
    assert _aggregate("sum", ["nan", "5", "1,000"]) == 1005


def test_export_keeps_codes_and_never_makes_a_formula() -> None:
    assert _num("007") == "007" and _num("0101") == "0101" and _num("-01") == "-01"
    assert _num("7") == 7 and _num("0") == 0 and _num("0.5") == 0.5 and _num("-0.5") == -0.5 and _num("1e3") == 1000
    from openpyxl import Workbook
    wb = Workbook()
    _put(wb.active, 1, 1, "=HYPERLINK(\"http://example.com\")")
    _put(wb.active, 1, 2, "plain")
    buf = io.BytesIO()
    wb.save(buf)
    ws = load_workbook(io.BytesIO(buf.getvalue())).active
    assert ws["A1"].data_type == "s" and ws["A1"].value == "=HYPERLINK(\"http://example.com\")"
    assert ws["B1"].value == "plain"
