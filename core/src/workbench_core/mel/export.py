# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Export the import result (combined table, or the load / instrument list) as CSV or .xlsx."""

from __future__ import annotations

import csv
import io
import re

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from .pipeline import LoadListResult, PipelineResult

HEADER = PatternFill("solid", fgColor="DDE4EE")
AUTO_HEADER = PatternFill("solid", fgColor="E1EAF6")
OVERRIDE = PatternFill("solid", fgColor="FCE3CC")
CUSTOM = PatternFill("solid", fgColor="E3F1E4")
ERROR = PatternFill("solid", fgColor="F8DEDE")
NUM_CHARS = set("0123456789.+-eE")
_LEADING_ZERO = re.compile(r"^[+-]?0\d")


def _num(text: str):
    """A cell's text as a number where it reads as one. "007" and "0101" stay text: they are
    codes, and a number would lose their leading zeros."""
    t = text.strip()
    if t and set(t) <= NUM_CHARS and not _LEADING_ZERO.match(t):
        try:
            f = float(t)
            return int(f) if f.is_integer() and "." not in t and "e" not in t.lower() else f
        except ValueError:
            pass
    return text


def _put(ws, row: int, column: int, value):
    """Write a cell. Text that starts with "=" stays text: it came from a file, and Excel must
    not run it as a formula."""
    cell = ws.cell(row=row, column=column, value=value)
    if isinstance(value, str) and value.startswith("="):
        cell.data_type = "s"
    return cell


def combined_csv(result: PipelineResult) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(result.headers)
    for r in result.rows:
        w.writerow([r.values.get(h, "") for h in result.headers])
    return buf.getvalue().encode("utf-8-sig")  # BOM so Excel opens it as UTF-8


def load_list_csv(ll: LoadListResult) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(ll.fields)
    for r in ll.rows:
        w.writerow(["" if r.get(f) is None else r.get(f) for f in ll.fields])
    return buf.getvalue().encode("utf-8-sig")


def _header(ws, names: list[str], fills: dict[str, PatternFill] | None = None) -> None:
    for c, name in enumerate(names, start=1):
        cell = ws.cell(row=1, column=c, value=name)
        cell.font = Font(bold=True)
        cell.fill = (fills or {}).get(name, HEADER)
        ws.column_dimensions[get_column_letter(c)].width = max(10, min(len(name) + 4, 40))
    ws.freeze_panes = "B2"


def combined_xlsx(result: PipelineResult, auto_columns: list[str], title: str) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Combined"
    _header(ws, result.headers, {h: AUTO_HEADER for h in auto_columns})
    for i, r in enumerate(result.rows, start=2):
        for c, h in enumerate(result.headers, start=1):
            cell = _put(ws, i, c, _num(r.values.get(h, "")))
            if h in r.overridden:
                cell.fill = OVERRIDE
                cell.comment = Comment("Overridden in the import recipe", "ECG Source List")
            elif h in r.auto_errors:
                cell.fill = ERROR
            elif r.origin == "custom":
                cell.fill = CUSTOM
    if result.rows:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(result.headers))}{len(result.rows) + 1}"
    _notes(wb, result, title)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def load_list_xlsx(ll: LoadListResult, result: PipelineResult, title: str, sheet: str = "Load list") -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    _header(ws, ll.fields)
    for i, r in enumerate(ll.rows, start=2):
        for c, f in enumerate(ll.fields, start=1):
            _put(ws, i, c, r.get(f))
    if ll.rows:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(ll.fields))}{len(ll.rows) + 1}"
    _notes(wb, result, title, ll.warnings)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _notes(wb: Workbook, result: PipelineResult, title: str, extra: list[str] | None = None) -> None:
    ws = wb.create_sheet("Notes")
    ws["A1"] = title
    ws["A1"].font = Font(bold=True, size=14)
    lines = [("Rows", len(result.rows)), ("Columns", len(result.headers)), ("Key column", result.key_header),
             ("Legend", "orange = overridden cell, green = custom row, red = calculation error")]
    lines += [("Warning", w) for w in extra or []]
    lines += [(f"Rule not applied ({i.kind})", f"{i.rule}: {i.message}") for i in result.issues]
    for r, (k, v) in enumerate(lines, start=3):
        ws.cell(row=r, column=1, value=k).font = Font(bold=True)
        ws.cell(row=r, column=2, value=v)
    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 80
