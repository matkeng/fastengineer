# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Text rules that must match the VBA engine exactly: value to text (PRD 5.4), literal
case-insensitive replacement (5.5), and Excel's "as typed" reading of a cell (5.7)."""

from __future__ import annotations

import math
import re
from datetime import date, datetime

from .models import Scalar

NO_VALUE = "<<No Value Found>>"
PARENT_NOT_FOUND = "<< Parent Not Found >>"
ERRORS = {"#N/A", "#VALUE!", "#REF!", "#DIV/0!", "#NUM!", "#NAME?", "#NULL!", "#SPILL!", "#CALC!", "#GETTING_DATA"}


def number_text(x: float) -> str:
    """VBA CStr of a Double: integers without a decimal point, others with up to 15
    significant digits and no trailing zeros (so 0.1+0.2 gives 0.3)."""
    if isinstance(x, bool):
        return "True" if x else "False"
    if isinstance(x, int):
        return str(x)
    if math.isnan(x) or math.isinf(x):
        return ""
    if x == int(x) and abs(x) < 1e15:
        return str(int(x))
    s = f"{x:.15g}"
    if "e" in s:  # VBA uses e.g. 1E-05 / 1.5E+20
        mant, exp = s.split("e")
        sign = "-" if exp.startswith("-") else "+"
        return f"{mant}E{sign}{int(exp.lstrip('+-')):02d}"
    return s


def to_text(v: Scalar, date_format: str = "%d/%m/%Y") -> str:
    """PRD 5.4 (VBA CStr semantics)."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "True" if v else "False"
    if isinstance(v, (int, float)):
        return number_text(v)
    if isinstance(v, datetime):
        if v.hour or v.minute or v.second:
            return v.strftime(date_format + " %H:%M:%S")
        return v.strftime(date_format)
    if isinstance(v, date):
        return v.strftime(date_format)
    s = str(v)
    return "" if s in ERRORS else s


def replace_ci(s: str, old: str, new: str) -> str:
    """Replace every occurrence of `old` ignoring case; `new` is inserted literally."""
    if not old:
        return s
    low, lold = s.lower(), old.lower()
    i = low.find(lold)
    if i < 0:
        return s
    out, start = [], 0
    while i >= 0:
        out.append(s[start:i])
        out.append(new)
        start = i + len(old)
        i = low.find(lold, start)
    out.append(s[start:])
    return "".join(out)


def contains_ci(s: str, part: str) -> bool:
    return part.lower() in s.lower()


def collapse_spaces(s: str, full: bool = False) -> str:
    """Compat: replace double spaces with one, three times (runs > 8 spaces survive,
    Appendix D item 7). Standard: collapse every run."""
    if full:
        return re.sub(r" {2,}", " ", s)
    for _ in range(3):
        s = s.replace("  ", " ")
    return s


_NUM = re.compile(r"^\s*[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?\s*$")
_DATE = re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*$")


def as_typed(s: str, from_literal: bool = False, literal_value: Scalar = None) -> Scalar:
    """How Excel reads a typed cell (PRD 5.7): number, TRUE/FALSE, d/m/yyyy date, else text.
    A template literal keeps its stored value and type (Appendix D item 12). Formulas are
    handled by the caller."""
    if from_literal:
        return literal_value
    if s == "":
        return None
    if _NUM.match(s):
        v = float(s)
        if v == int(v) and "." not in s and "e" not in s.lower():
            return int(v)
        return int(v) if v == int(v) and abs(v) < 1e15 else v
    up = s.strip().upper()
    if up == "TRUE":
        return True
    if up == "FALSE":
        return False
    m = _DATE.match(s)
    if m:
        d, mo, y = (int(g) for g in m.groups())
        try:
            return date(y, mo, d)
        except ValueError:
            return s
    return s


TRUTHY = {"true", "yes", "y", "1", "x", "locked"}


def is_truthy(v: Scalar) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v == 1
    return str(v or "").strip().lower() in TRUTHY
