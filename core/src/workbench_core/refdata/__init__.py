# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""User-defined reference data: enumerated lists, trees and typed tables.

Lists (enums) hold items with a unique code and value plus a description.
Trees are lists whose items have a parent item (a self-reference).
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
    RefTree,
    RefValidationError,
    TreeNode,
)
from .validate import check_enum, check_table_columns, check_tree, convert_rows, name_key, tree_depth, validate_row

__all__ = [
    "COLUMN_TYPES", "ColumnDef", "EnumItem", "EnumList", "RefRow", "RefTable", "RefTree", "RefValidationError",
    "TreeNode", "check_enum", "check_table_columns", "check_tree", "convert_rows", "name_key", "tree_depth",
    "validate_row",
]
