# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""User-defined reference data: enumerated lists and typed tables.

Lists (enums) hold items with a unique code and value plus a description.
Tables have typed columns (text, enum, integer, boolean, decimal) and rows.
Enum cells store the item's id, so editing an item's code or value never
breaks the rows that use it.
"""

from .models import (
    COLUMN_TYPES,
    ColumnDef,
    EnumItem,
    EnumList,
    RefRow,
    RefTable,
    RefValidationError,
)
from .validate import check_enum, check_table_columns, convert_rows, name_key, validate_row

__all__ = [
    "COLUMN_TYPES", "ColumnDef", "EnumItem", "EnumList", "RefRow", "RefTable", "RefValidationError",
    "check_enum", "check_table_columns", "convert_rows", "name_key", "validate_row",
]
