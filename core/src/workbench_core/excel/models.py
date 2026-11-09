# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

Strike = Literal["none", "partial", "full"]
Scalar = str | int | float | bool | None


class StrikeRun(BaseModel):
    text: str
    strike: bool


class CellOut(BaseModel):
    """One cell, after formula calculation and merged-cell expansion."""

    v: Scalar  # value (dates as ISO strings)
    t: str  # display text
    s: Strike = "none"
    runs: list[StrikeRun] | None = None  # only for partial strike
    m: bool = False  # True if the value was copied from a merged range


class SourceInfo(BaseModel):
    """A queryable source: a whole worksheet or a defined Excel table."""

    id: str  # "sheet:<name>" or "table:<name>"
    kind: Literal["sheet", "table"]
    name: str
    sheet: str
    ref: str  # e.g. "A1:H120"
    first_row: int
    last_row: int
    first_col: int
    last_col: int


class WorkbookSummary(BaseModel):
    id: str
    filename: str
    sources: list[SourceInfo]
    warnings: list[str] = []


class PreviewRow(BaseModel):
    row: int  # Excel row number
    cells: list[CellOut]
    filled: int  # non-empty cells


class PreviewResult(BaseModel):
    source: SourceInfo
    columns: list[str]  # Excel column letters
    rows: list[PreviewRow]
    suggested_header_row: int | None
    suggested_header_rows: int = 1
    truncated: bool


class ColumnInfo(BaseModel):
    index: int  # 0-based position in the extracted table
    letter: str  # Excel column letter
    name: str  # header text, de-duplicated
    non_blank: int
    unique: int
    duplicates: int  # non-blank values that occur more than once


class ColumnsResult(BaseModel):
    source: SourceInfo
    header_row: int
    header_rows: int = 1
    data_rows: int
    columns: list[ColumnInfo]
    suggested_key: int | None


class ExtractedRow(BaseModel):
    row: int  # Excel row number
    key: str
    strike: Strike  # row-level: full if every non-empty cell is fully struck
    duplicate_key: bool
    cells: list[CellOut]


class ExtractResult(BaseModel):
    source: SourceInfo
    header_row: int
    header_rows: int = 1
    key_column: int
    columns: list[ColumnInfo]
    rows: list[ExtractedRow]
    blank_keys_skipped: int
    duplicate_keys: list[str]
    warnings: list[str] = []
