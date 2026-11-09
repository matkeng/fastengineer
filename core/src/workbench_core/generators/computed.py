# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Computed columns (PRD 7.2): the declarative replacement for template formulas."""

from __future__ import annotations

from collections.abc import Callable

from .expr import ExprError, _text as excel_text, evaluate
from .models import Concat, Count, Exists, Expr, Lookup, RefTable, Scalar
from .text import ERRORS, to_text

NA = "#N/A"


def is_error(v: Scalar) -> bool:
    return isinstance(v, str) and v in ERRORS


def _key(v: Scalar) -> str:
    """VLOOKUP exact match: case-insensitive, no trimming."""
    return to_text(v).lower()


class TableIndex:
    """Fast lookups on a reference table: first match wins, case-insensitive (VLOOKUP exact)."""

    def __init__(self, table: RefTable):
        self.table = table
        self.col = {c.lower(): i for i, c in enumerate(table.columns)}
        self._exact: dict[int, dict[str, int]] = {}
        self._approx: dict[int, dict] = {}
        self._approx_vals: dict[int, list] = {}

    def column_index(self, name: str) -> int:
        try:
            return self.col[name.lower()]
        except KeyError as exc:
            raise KeyError(f"Table '{self.table.name}' has no column '{name}'") from exc

    def find(self, col: str, value: Scalar) -> int | None:
        ci = self.column_index(col)
        idx = self._exact.get(ci)
        if idx is None:
            idx = {}
            for r, row in enumerate(self.table.rows):
                k = _key(row[ci] if ci < len(row) else None)
                idx.setdefault(k, r)
            self._exact[ci] = idx
        return idx.get(_key(value))

    def value(self, r: int, col: str) -> Scalar:
        ci = self.column_index(col)
        row = self.table.rows[r]
        return row[ci] if ci < len(row) else None

    def approx_match(self, col: str, value: Scalar) -> Scalar:
        """VLOOKUP(value, col, 1) with approximate match: Excel's binary search for the largest
        entry <= value (meaningful only when the column is sorted ascending)."""
        ci = self.column_index(col)
        memo = self._approx.setdefault(ci, {})
        mk = (type(value).__name__, to_text(value))
        if mk in memo:
            return memo[mk]
        vals = self._approx_vals.get(ci)
        if vals is None:
            vals = [row[ci] if ci < len(row) else None for row in self.table.rows]
            vals = self._approx_vals[ci] = [v for v in vals if v is not None and to_text(v) != ""]

        def less_eq(a: Scalar, b: Scalar) -> bool:  # Excel order: numbers < text, text case-insensitive
            an, bn = isinstance(a, (int, float)) and not isinstance(a, bool), isinstance(b, (int, float)) and not isinstance(b, bool)
            if an and bn:
                return a <= b
            if an != bn:
                return an
            return to_text(a).lower() <= to_text(b).lower()

        lo, hi, found = 0, len(vals) - 1, None
        while lo <= hi:
            mid = (lo + hi) // 2
            if less_eq(vals[mid], value):
                found = vals[mid]
                lo = mid + 1
            else:
                hi = mid - 1
        memo[mk] = NA if found is None else found
        return memo[mk]

    def count(self, col: str, value: Scalar) -> int:
        ci = self.column_index(col)
        k = _key(value)
        return sum(1 for row in self.table.rows if _key(row[ci] if ci < len(row) else None) == k)


def evaluate_computed(c, row_value: Callable[[str], Scalar], tables: dict[str, TableIndex], standard: bool) -> Scalar:
    """Excel semantics: an error in any referenced cell propagates (#N/A stays #N/A)."""
    try:
        return _evaluate(c, row_value, tables, standard)
    except KeyError:
        return "#REF!"  # missing table or column (reported by Check C17)


def _evaluate(c, row_value, tables, standard):
    if not isinstance(c, Expr):
        for d in dependencies(c):
            v = row_value(d)
            if is_error(v):
                return v
    if isinstance(c, Concat):
        return "".join(p if isinstance(p, str) else excel_text(row_value(p["col"])) for p in c.parts)
    if isinstance(c, Exists):
        x = row_value(c.value)
        t = tables[c.table]
        if standard or not c.approximate:
            return t.find(c.column, x) is not None
        found = t.approx_match(c.column, x)
        if found == NA:
            return NA
        return to_text(found) == to_text(x)  # EXACT: case-sensitive
    if isinstance(c, Lookup):
        if c.guard_column is not None and to_text(row_value(c.guard_column)) == "":
            return ""
        key = row_value(c.key)
        if to_text(key) == "" and c.if_key_blank == "blank":
            return ""
        t = tables[c.table]
        r = t.find(c.key_column, key)
        if r is None:
            return NA
        v = t.value(r, c.return_column)
        return 0 if v is None else v  # VLOOKUP of an empty cell returns 0
    if isinstance(c, Count):
        return tables[c.table].count(c.column, row_value(c.equals))
    if isinstance(c, Expr):
        try:
            return evaluate(c.expression, refs=row_value)
        except ExprError as exc:
            return f"#ERROR: {exc}"
    raise TypeError(f"Unknown computed column {c!r}")


def dependencies(c) -> list[str]:
    import re
    if isinstance(c, Concat):
        return [p["col"] for p in c.parts if isinstance(p, dict)]
    if isinstance(c, Exists):
        return [c.value]
    if isinstance(c, Lookup):
        return [c.key] + ([c.guard_column] if c.guard_column else [])
    if isinstance(c, Count):
        return [c.equals]
    if isinstance(c, Expr):
        return re.findall(r"\[([^\]]*)\]", c.expression)
    return []
