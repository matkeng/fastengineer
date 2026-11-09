"""Excel query and table extraction (spec section 6).

Reads cached (calculated) values, expands merged cells and detects full and
partial strikethrough, so a worksheet or Excel table can be turned into a
keyed table for review.
"""

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
