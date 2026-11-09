# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Excel query and table extraction (spec section 6).

Reads cached (calculated) values, expands merged cells and detects full and
partial strikethrough, so a worksheet or Excel table can be turned into a
keyed table for review.
"""

from .compare import CompareOptions, CompareResult, compare_tables
from .export import compare_to_xlsx
from .models import (
    CellOut,
    ColumnInfo,
    ColumnsResult,
    ExtractResult,
    PreviewResult,
    SourceInfo,
    StrikeRun,
    WorkbookSummary,
)
from .reader import ExcelError, Workbook

__all__ = [
    "CompareOptions",
    "CompareResult",
    "compare_tables",
    "compare_to_xlsx",
    "CellOut",
    "ColumnInfo",
    "ColumnsResult",
    "ExcelError",
    "ExtractResult",
    "PreviewResult",
    "SourceInfo",
    "StrikeRun",
    "Workbook",
    "WorkbookSummary",
]
