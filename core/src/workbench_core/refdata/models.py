from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ColumnType = Literal["text", "enum", "integer", "boolean", "decimal"]
COLUMN_TYPES: list[str] = ["text", "enum", "integer", "boolean", "decimal"]
CellValue = str | int | bool | None  # decimals are kept as normalised strings (exact)


def new_id() -> str:
    return uuid.uuid4().hex


class RefValidationError(ValueError):
    """User-facing validation problem; `fields` maps a field/column/item to its message."""

    def __init__(self, message: str, fields: dict[str, str] | None = None):
        super().__init__(message)
        self.message = message
        self.fields = fields or {}


class EnumItem(BaseModel):
    id: str = Field(default_factory=new_id)
    code: str
    value: str
    description: str = ""


class EnumList(BaseModel):
    id: str = Field(default_factory=new_id)
    name: str
    description: str = ""
    items: list[EnumItem] = Field(default_factory=list)
    updated_at: datetime | None = None


class ColumnDef(BaseModel):
    id: str = Field(default_factory=new_id)
    name: str
    type: ColumnType = "text"
    enum_id: str | None = None  # for type "enum"
    required: bool = False
    unique: bool = False


class RefTable(BaseModel):
    id: str = Field(default_factory=new_id)
    name: str
    description: str = ""
    columns: list[ColumnDef] = Field(default_factory=list)
    updated_at: datetime | None = None


class RefRow(BaseModel):
    id: str = Field(default_factory=new_id)
    values: dict[str, CellValue] = Field(default_factory=dict)  # column id -> value
    updated_at: datetime | None = None
