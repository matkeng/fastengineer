# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
from __future__ import annotations

import io
import re
from collections import Counter
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

import openpyxl
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.utils import get_column_letter, range_boundaries
from openpyxl.worksheet.worksheet import Worksheet

from .models import (
    CellOut,
    ColumnInfo,
    ColumnsResult,
    ExtractedRow,
    ExtractResult,
    PreviewResult,
    PreviewRow,
    SourceInfo,
    StrikeRun,
    WorkbookSummary,
)

SUPPORTED_SUFFIXES = (".xlsx", ".xlsm", ".xltx", ".xltm")

# Words that often appear in engineering table headers; used to suggest the header row.
HEADER_HINTS = re.compile(
    r"\b(tag|no\.?|number|id|from|to|size|cores?|kw|kva|description|desc|type|"
    r"rating|voltage|v|length|qty|quantity|area|service|status|rev|remarks?|notes?)\b",
    re.I,
)
KEY_HINTS = re.compile(r"\b(tag|id|no\.?|number|key|ref|code)\b", re.I)
MAX_HEADER_ROWS = 4


class ExcelError(ValueError):
    """A user-facing problem with the workbook or the request."""


def _scalar(value: Any) -> tuple[Any, str]:
    """Convert a cell value to a JSON-friendly value and display text."""
    if value is None:
        return None, ""
    if isinstance(value, bool):
        return value, "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return value, str(value)
    if isinstance(value, float):
        text = repr(value)
        if text.endswith(".0"):
            text = text[:-2]
        return value, text
    if isinstance(value, Decimal):
        return float(value), str(value)
    if isinstance(value, datetime):
        if value.time() == time(0):
            return value.date().isoformat(), value.date().isoformat()
        iso = value.isoformat(sep=" ", timespec="seconds")
        return iso, iso
    if isinstance(value, (date, time)):
        iso = value.isoformat()
        return iso, iso
    if isinstance(value, timedelta):
        return value.total_seconds(), str(value)
    text = str(value)
    return text, text


def _read_cell(cell: Any) -> CellOut:
    value = cell.value
    cell_strike = bool(cell.font is not None and cell.font.strike)

    if isinstance(value, CellRichText):
        runs: list[StrikeRun] = []
        for part in value:
            if isinstance(part, TextBlock):
                # A run with its own formatting (<rPr>) is fully specified, as in
                # Excel: no <strike> means not struck, whatever the cell font says.
                runs.append(StrikeRun(text=part.text, strike=bool(part.font.strike)))
            else:  # a bare run uses the cell font
                runs.append(StrikeRun(text=str(part), strike=cell_strike))
        text = "".join(r.text for r in runs)
        visible = [r for r in runs if r.text.strip()]
        struck = [r for r in visible if r.strike]
        if not visible or not struck:
            return CellOut(v=text, t=text, s="full" if cell_strike and visible else "none")
        if len(struck) == len(visible):
            return CellOut(v=text, t=text, s="full")
        return CellOut(v=text, t=text, s="partial", runs=_merge_runs(runs))

    v, t = _scalar(value)
    return CellOut(v=v, t=t, s="full" if cell_strike and t.strip() else "none")


def _merge_runs(runs: list[StrikeRun]) -> list[StrikeRun]:
    merged: list[StrikeRun] = []
    for run in runs:
        if merged and merged[-1].strike == run.strike:
            merged[-1] = StrikeRun(text=merged[-1].text + run.text, strike=run.strike)
        elif run.text:
            merged.append(run)
    return merged


class _SheetGrid:
    """Cell access for one worksheet with merged ranges expanded."""

    def __init__(self, ws: Worksheet):
        self.ws = ws
        self._merged: dict[tuple[int, int], tuple[int, int]] = {}
        for rng in ws.merged_cells.ranges:
            min_col, min_row, max_col, max_row = rng.bounds
            for r in range(min_row, max_row + 1):
                for c in range(min_col, max_col + 1):
                    if (r, c) != (min_row, min_col):
                        self._merged[(r, c)] = (min_row, min_col)
        self._cache: dict[tuple[int, int], CellOut] = {}

    def cell(self, row: int, col: int) -> CellOut:
        key = (row, col)
        if key in self._cache:
            return self._cache[key]
        anchor = self._merged.get(key)
        if anchor:
            out = self.cell(*anchor).model_copy(update={"m": True})
        else:
            out = _read_cell(self.ws.cell(row=row, column=col))
        self._cache[key] = out
        return out

    def row(self, row: int, first_col: int, last_col: int) -> list[CellOut]:
        return [self.cell(row, c) for c in range(first_col, last_col + 1)]


def _filled(cells: list[CellOut]) -> int:
    return sum(1 for c in cells if c.t.strip())


class Workbook:
    """A loaded workbook. Load once, then preview, list columns and extract."""

    def __init__(self, data: bytes, filename: str, workbook_id: str):
        if not filename.lower().endswith(SUPPORTED_SUFFIXES):
            raise ExcelError(
                f"'{filename}' is not supported yet. Use .xlsx or .xlsm "
                "(strikethrough and merged cells need the Office Open XML format)."
            )
        try:
            # data_only=True returns the values Excel calculated and cached
            # when the file was last saved, not the formulas.
            self._wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, rich_text=True)
        except Exception as exc:  # openpyxl raises many types for corrupt files
            raise ExcelError(f"Could not read '{filename}': {exc}") from exc
        self.id = workbook_id
        self.filename = filename
        self._grids: dict[str, _SheetGrid] = {}
        self._warnings = self._formula_warnings(data)
        self.sources = self._find_sources()

    # -- discovery ---------------------------------------------------------

    def _formula_warnings(self, data: bytes) -> list[str]:
        """Warn if formulas have no cached result (file never calculated/saved by Excel)."""
        try:
            formulas = openpyxl.load_workbook(io.BytesIO(data), read_only=True)
        except Exception:
            return []
        missing = 0
        try:
            for ws in formulas.worksheets:
                values = self._wb[ws.title]
                for row in ws.iter_rows():
                    for cell in row:
                        if (
                            isinstance(cell.value, str)
                            and cell.value.startswith("=")
                            and values.cell(row=cell.row, column=cell.column).value is None
                        ):
                            missing += 1
        finally:
            formulas.close()
        if not missing:
            return []
        return [
            f"{missing} formula cell(s) have no calculated value saved in the file and will "
            "appear blank. Open and save the workbook in Excel to refresh them."
        ]

    def _find_sources(self) -> list[SourceInfo]:
        sources: list[SourceInfo] = []
        for ws in self._wb.worksheets:
            if ws.max_row > 1 or ws.max_column > 1 or ws["A1"].value is not None:
                sources.append(self._source("sheet", ws.title, ws.title, ws.calculate_dimension()))
            for table in ws.tables.values():
                sources.append(self._source("table", table.displayName or table.name, ws.title, table.ref))
        if not sources:
            raise ExcelError("The workbook has no worksheets with data.")
        return sources

    @staticmethod
    def _source(kind: str, name: str, sheet: str, ref: str) -> SourceInfo:
        min_col, min_row, max_col, max_row = range_boundaries(ref)
        return SourceInfo(
            id=f"{kind}:{name}", kind=kind, name=name, sheet=sheet, ref=ref,
            first_row=min_row, last_row=max_row, first_col=min_col, last_col=max_col,
        )

    def summary(self) -> WorkbookSummary:
        return WorkbookSummary(id=self.id, filename=self.filename, sources=self.sources,
                               warnings=self._warnings)

    def source(self, source_id: str) -> SourceInfo:
        for s in self.sources:
            if s.id == source_id:
                return s
        raise ExcelError(f"Unknown sheet or table: {source_id}")

    def _grid(self, sheet: str) -> _SheetGrid:
        if sheet not in self._grids:
            self._grids[sheet] = _SheetGrid(self._wb[sheet])
        return self._grids[sheet]

    # -- step 1: preview to choose the header row ----------------------------

    def preview(self, source_id: str, max_rows: int = 60) -> PreviewResult:
        src = self.source(source_id)
        grid = self._grid(src.sheet)
        last = min(src.last_row, src.first_row + max_rows - 1)
        rows = []
        for r in range(src.first_row, last + 1):
            cells = grid.row(r, src.first_col, src.last_col)
            rows.append(PreviewRow(row=r, cells=cells, filled=_filled(cells)))
        header, depth = (src.first_row, 1) if src.kind == "table" else self._suggest_header(rows)
        return PreviewResult(
            source=src,
            columns=[get_column_letter(c) for c in range(src.first_col, src.last_col + 1)],
            rows=rows,
            suggested_header_row=header,
            suggested_header_rows=depth,
            truncated=last < src.last_row,
        )

    @staticmethod
    def _suggest_header(rows: list[PreviewRow]) -> tuple[int | None, int]:
        """Pick the header row: mostly text, many filled cells, header-like words,
        data below. Then extend it upwards over rows merged down into it, so a
        stacked header ("Cable" over "Size", "Cores") is taken as one."""
        best, best_score, best_i = None, 0.0, 0
        widest = max((r.filled for r in rows), default=0)
        if not widest:
            return None, 1
        for i, r in enumerate(rows[:30]):
            texts = [c for c in r.cells if c.t.strip()]
            if len(texts) < max(2, widest * 0.5):
                continue
            text_ratio = sum(isinstance(c.v, str) for c in texts) / len(texts)
            hints = sum(bool(HEADER_HINTS.search(c.t)) for c in texts)
            below = rows[i + 1 : i + 4]
            data_below = sum(b.filled >= len(texts) * 0.5 for b in below)
            score = len(texts) / widest + 2 * text_ratio + 0.5 * hints + 0.5 * data_below
            if score > best_score:
                best, best_score, best_i = r.row, score, i
        if best is None:
            return None, 1
        top = best_i
        while top > 0 and best_i - top + 1 < MAX_HEADER_ROWS and any(
            c.m and c.t.strip() and c.t == above.t
            for c, above in zip(rows[top].cells, rows[top - 1].cells)
        ):
            top -= 1
        return rows[top].row, best_i - top + 1

    # -- step 2: columns to choose the key ----------------------------------

    def _header_and_data(self, src: SourceInfo, header_row: int, header_rows: int = 1):
        if not 1 <= header_rows <= MAX_HEADER_ROWS:
            raise ExcelError(f"A header can span 1 to {MAX_HEADER_ROWS} rows.")
        last_header = header_row + header_rows - 1
        if not (src.first_row <= header_row and last_header <= src.last_row):
            raise ExcelError(f"Header rows {header_row}-{last_header} are outside {src.ref}.")
        grid = self._grid(src.sheet)
        stacked = [grid.row(r, src.first_col, src.last_col) for r in range(header_row, last_header + 1)]
        header = []
        for i in range(src.last_col - src.first_col + 1):
            # Join stacked header parts, skipping repeats from vertical merges.
            parts: list[str] = []
            for row in stacked:
                text = " ".join(row[i].t.split())
                if text and (not parts or parts[-1] != text):
                    parts.append(text)
            header.append(" ".join(parts))
        data = []
        for r in range(last_header + 1, src.last_row + 1):
            cells = grid.row(r, src.first_col, src.last_col)
            if _filled(cells):
                data.append((r, cells))

        # Drop columns with no header and no data at all.
        keep = [
            i for i in range(len(header))
            if header[i] or any(cells[i].t.strip() for _, cells in data)
        ]
        names, seen = [], Counter()
        for i in keep:
            letter = get_column_letter(src.first_col + i)
            base = header[i] or f"Column {letter}"
            seen[base] += 1
            names.append(base if seen[base] == 1 else f"{base} ({seen[base]})")

        columns = []
        for pos, (i, name) in enumerate(zip(keep, names)):
            values = [cells[i].t.strip() for _, cells in data if cells[i].t.strip()]
            counts = Counter(values)
            columns.append(ColumnInfo(
                index=pos, letter=get_column_letter(src.first_col + i), name=name,
                non_blank=len(values), unique=len(counts),
                duplicates=sum(n for n in counts.values() if n > 1),
            ))
        rows = [(r, [cells[i] for i in keep]) for r, cells in data]
        return columns, rows

    def columns(self, source_id: str, header_row: int, header_rows: int = 1) -> ColumnsResult:
        src = self.source(source_id)
        columns, rows = self._header_and_data(src, header_row, header_rows)
        if not columns:
            raise ExcelError("No columns found below that header row.")
        return ColumnsResult(source=src, header_row=header_row, header_rows=header_rows,
                             data_rows=len(rows), columns=columns,
                             suggested_key=self._suggest_key(columns, len(rows)))

    @staticmethod
    def _suggest_key(columns: list[ColumnInfo], data_rows: int) -> int | None:
        """Prefer mostly-unique, well-filled, left-hand columns named like a tag or ID."""
        if not data_rows:
            return None

        def score(c: ColumnInfo) -> float:
            return (c.unique / data_rows + 0.3 * bool(KEY_HINTS.search(c.name))
                    - 0.05 * c.index)

        return max(columns, key=score).index

    # -- step 3: extract the keyed table -------------------------------------

    def extract(self, source_id: str, header_row: int, key_column: int,
                header_rows: int = 1, skip_blank_keys: bool = True) -> ExtractResult:
        src = self.source(source_id)
        columns, rows = self._header_and_data(src, header_row, header_rows)
        if not 0 <= key_column < len(columns):
            raise ExcelError("Key column is out of range.")

        out: list[ExtractedRow] = []
        skipped = 0
        for r, cells in rows:
            key = cells[key_column].t.strip()
            if not key and skip_blank_keys:
                skipped += 1
                continue
            filled = [c for c in cells if c.t.strip()]
            if filled and all(c.s == "full" for c in filled):
                strike = "full"
            elif any(c.s != "none" for c in filled):
                strike = "partial"
            else:
                strike = "none"
            out.append(ExtractedRow(row=r, key=key, strike=strike, duplicate_key=False, cells=cells))

        counts = Counter(row.key for row in out if row.key)
        dupes = sorted(k for k, n in counts.items() if n > 1)
        for row in out:
            row.duplicate_key = counts.get(row.key, 0) > 1

        warnings = list(self._warnings)
        if dupes:
            warnings.append(f"{len(dupes)} key value(s) appear more than once.")
        return ExtractResult(
            source=src, header_row=header_row, header_rows=header_rows,
            key_column=key_column, columns=columns,
            rows=out, blank_keys_skipped=skipped, duplicate_keys=dupes, warnings=warnings,
        )
