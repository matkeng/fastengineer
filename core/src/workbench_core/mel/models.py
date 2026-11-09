# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

TargetList = Literal["MEL", "ELL", "EEL", "PIL", "LIL"]

# Load-list fields a recipe maps onto (PRD 5.11). Numeric ones are coerced on output.
ELEC_LOAD_FIELDS: list[str] = [
    "area", "sub_area", "tag", "equip_qty", "standby_qty", "multi_load", "desc",
    "equip_type", "equip_subtype", "load_units", "load_rating", "load_voltage",
    "csv_row_num", "phases", "status", "starter_type", "load_type", "starter_addons",
    "load_addons", "field_addons", "is_a_loadcentre", "loadcentre", "supplied_from",
    "is_deleted",
]
NUMERIC_FIELDS = {"equip_qty", "standby_qty", "load_rating", "load_voltage", "csv_row_num", "phases"}

# Instrument-list fields a PIL recipe maps onto (fed by the P&ID tags list).
INSTRUMENT_FIELDS: list[str] = [
    "tag", "function", "loop", "suffix", "desc", "service", "instrument_type", "area",
    "pid_drawing", "pid_sheet", "line_number", "equipment", "signal_type", "io_system",
    "range_min", "range_max", "units", "manufacturer", "model", "status", "is_deleted",
]

# What each target list maps onto. Targets without their own list use the load list.
TARGET_FIELDS: dict[str, list[str]] = {"MEL": ELEC_LOAD_FIELDS, "PIL": INSTRUMENT_FIELDS}
TARGET_NUMERIC: dict[str, set[str]] = {"MEL": NUMERIC_FIELDS, "PIL": {"range_min", "range_max"}}
TARGET_BOOLEAN: dict[str, set[str]] = {"MEL": {"is_a_loadcentre", "is_deleted"}, "PIL": {"is_deleted"}}
TARGET_OUTPUT: dict[str, str] = {"MEL": "Load list", "PIL": "Instrument list"}


def fields_for(target: str) -> list[str]:
    return TARGET_FIELDS.get(target, ELEC_LOAD_FIELDS)


def output_name(target: str) -> str:
    return TARGET_OUTPUT.get(target, "Load list")


class ColumnRule(BaseModel):
    """Hide and/or rename a source column (PRD 5.4). Keyed by the source header."""
    header: str
    visible: bool = True
    rename: str | None = None


class RowRule(BaseModel):
    """Hide a row, keyed by its key-column value (PRD 5.5)."""
    key: str


class TextColumn(BaseModel):
    """A column with the same value in every row (PRD 5.6)."""
    name: str
    value: str = ""


class Override(BaseModel):
    """Replace one cell, keyed by (row key, column name) (PRD 5.7)."""
    key: str
    column: str
    value: str


class CustomRow(BaseModel):
    """A hand-entered row appended to the list (PRD 5.8)."""
    key: str
    values: dict[str, str] = Field(default_factory=dict)


class AutoColumn(BaseModel):
    """A calculated column (PRD 5.9). `<<Column>>` refers to a column's value."""
    name: str
    statement: str = "True"
    true_val: str = ""
    false_val: str = ""
    error_val: str = "ERROR"


class FieldMap(BaseModel):
    """Load-list field <- output column, or a manual constant (PRD 5.11)."""
    field: str
    column: str | None = None
    manual: str | None = None


class Recipe(BaseModel):
    """Everything the user decides. Saved as one document, so a save is atomic."""
    id: str
    name: str
    target: TargetList = "MEL"
    columns: list[ColumnRule] = Field(default_factory=list)
    hidden_rows: list[RowRule] = Field(default_factory=list)
    text_columns: list[TextColumn] = Field(default_factory=list)
    overrides: list[Override] = Field(default_factory=list)
    custom_rows: list[CustomRow] = Field(default_factory=list)
    auto_columns: list[AutoColumn] = Field(default_factory=list)  # evaluated in list order
    mapping: list[FieldMap] = Field(default_factory=list)
    updated_at: datetime | None = None


class RevisionInfo(BaseModel):
    id: str
    rev: int
    file_name: str
    source: str  # "csv" or "excel: <sheet/table>"
    key_header: str
    num_rows: int  # data rows (header not counted)
    num_cols: int
    uploaded_at: datetime
    warnings: list[str] = Field(default_factory=list)


class Revision(RevisionInfo):
    headers: list[str]  # unique, stripped
    headers_original: list[str]
    rows: list[dict[str, str]]  # keyed by `headers`; key values made unique
