# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Lists (enums) and tables: CRUD endpoints over workbench_core.refdata."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from workbench_core.refdata import (
    COLUMN_TYPES,
    ColumnDef,
    EnumItem,
    EnumList,
    RefRow,
    RefTable,
    RefValidationError,
    check_enum,
    check_table_columns,
    convert_rows,
    validate_row,
)

from .storage import NotFound, get_ref

router = APIRouter(prefix="/api/ref", tags=["reference data"])


def invalid(exc: RefValidationError) -> JSONResponse:
    """422 with a message and per-field messages the UI shows next to each input."""
    return JSONResponse(status_code=422, content={"detail": exc.message, "fields": exc.fields})


def _not_found(what: str) -> HTTPException:
    return HTTPException(404, f"That {what} no longer exists.")


class NewObject(BaseModel):
    name: str
    description: str = ""


# -- overview -------------------------------------------------------------------

@router.get("")
def overview() -> dict:
    ref = get_ref()
    enums = ref.enums()
    counts = ref.row_counts()
    used: dict[str, list[str]] = {}
    for t in ref.tables():
        for c in t.columns:
            if c.type == "enum" and c.enum_id:
                used.setdefault(c.enum_id, []).append(f"{t.name}.{c.name}")
    return {
        "enums": sorted(({"id": e.id, "name": e.name, "description": e.description, "items": len(e.items),
                          "used_by": used.get(e.id, [])} for e in enums.values()), key=lambda x: x["name"].casefold()),
        "tables": sorted(({"id": t.id, "name": t.name, "description": t.description, "columns": len(t.columns),
                           "rows": counts.get(t.id, 0)} for t in ref.tables()), key=lambda x: x["name"].casefold()),
        "column_types": COLUMN_TYPES,
    }


# -- lists --------------------------------------------------------------------

@router.post("/enums", response_model=EnumList)
def create_enum(body: NewObject):
    try:
        return get_ref().save_enum(check_enum(EnumList(name=body.name, description=body.description)), create=True)
    except RefValidationError as exc:
        return invalid(exc)


@router.get("/enums/{enum_id}", response_model=EnumList)
def get_enum(enum_id: str) -> EnumList:
    try:
        return get_ref().get_enum(enum_id)
    except NotFound as exc:
        raise _not_found("list") from exc


class EnumUpdate(BaseModel):
    name: str
    description: str = ""
    items: list[EnumItem]


def _enum_usage(enum_id: str) -> tuple[list[str], dict[str, int]]:
    """Columns that use the list, and how many cells use each item."""
    ref = get_ref()
    columns, per_item = [], {}
    for t in ref.tables():
        cols = [c for c in t.columns if c.type == "enum" and c.enum_id == enum_id]
        if not cols:
            continue
        columns += [f"{t.name}.{c.name}" for c in cols]
        for r in ref.rows(t.id):
            for c in cols:
                v = r.values.get(c.id)
                if v is not None:
                    per_item[v] = per_item.get(v, 0) + 1
    return columns, per_item


@router.put("/enums/{enum_id}", response_model=EnumList)
def update_enum(enum_id: str, body: EnumUpdate):
    ref = get_ref()
    try:
        old = ref.get_enum(enum_id)
    except NotFound as exc:
        raise _not_found("list") from exc
    try:
        enum = check_enum(EnumList(id=enum_id, name=body.name, description=body.description, items=body.items))
        removed = {i.id for i in old.items} - {i.id for i in enum.items}
        if removed:
            _, per_item = _enum_usage(enum_id)
            in_use = {i.code: per_item[i.id] for i in old.items if i.id in removed and per_item.get(i.id)}
            if in_use:
                raise RefValidationError(
                    "These items are used in table rows and can't be deleted: "
                    + ", ".join(f"{c} ({n} row{'s' if n > 1 else ''})" for c, n in in_use.items())
                    + ". Change those rows first.")
        return ref.save_enum(enum)
    except RefValidationError as exc:
        return invalid(exc)


@router.delete("/enums/{enum_id}")
def delete_enum(enum_id: str):
    columns, _ = _enum_usage(enum_id)
    if columns:
        return invalid(RefValidationError(
            f"This list is used by column(s) {', '.join(columns)}. Change or delete those columns first."))
    get_ref().delete_enum(enum_id)
    return {"status": "deleted"}


# -- tables -------------------------------------------------------------------

@router.post("/tables", response_model=RefTable)
def create_table(body: NewObject):
    ref = get_ref()
    try:
        table = check_table_columns(RefTable(name=body.name, description=body.description), ref.enums())
        return ref.save_table(table, create=True)
    except RefValidationError as exc:
        return invalid(exc)


class TableDetail(BaseModel):
    table: RefTable
    rows: list[RefRow]
    enums: dict[str, EnumList]  # lists used by the table's columns


def _detail(table_id: str) -> TableDetail:
    ref = get_ref()
    try:
        table = ref.get_table(table_id)
    except NotFound as exc:
        raise _not_found("table") from exc
    enums = ref.enums()
    used = {c.enum_id for c in table.columns if c.enum_id}
    return TableDetail(table=table, rows=ref.rows(table_id), enums={k: v for k, v in enums.items() if k in used})


@router.get("/tables/{table_id}", response_model=TableDetail)
def get_table(table_id: str) -> TableDetail:
    return _detail(table_id)


class TableUpdate(BaseModel):
    name: str
    description: str = ""
    columns: list[ColumnDef]


@router.put("/tables/{table_id}", response_model=TableDetail)
def update_table(table_id: str, body: TableUpdate):
    """Rename / change columns. Existing rows are converted, or nothing is saved."""
    ref = get_ref()
    try:
        old = ref.get_table(table_id)
    except NotFound as exc:
        raise _not_found("table") from exc
    enums = ref.enums()
    try:
        new = check_table_columns(RefTable(id=table_id, name=body.name, description=body.description,
                                           columns=body.columns), enums)
        rows = convert_rows(old, new, ref.rows(table_id), enums)
        ref.save_table(new, rows)
    except RefValidationError as exc:
        return invalid(exc)
    return _detail(table_id)


@router.delete("/tables/{table_id}")
def delete_table(table_id: str) -> dict[str, str]:
    get_ref().delete_table(table_id)
    return {"status": "deleted"}


# -- rows ---------------------------------------------------------------------

class RowValues(BaseModel):
    values: dict[str, object]


def _row_context(table_id: str):
    ref = get_ref()
    try:
        return ref, ref.get_table(table_id), ref.enums(), ref.rows(table_id)
    except NotFound as exc:
        raise _not_found("table") from exc


@router.post("/tables/{table_id}/rows", response_model=RefRow)
def add_row(table_id: str, body: RowValues):
    ref, table, enums, rows = _row_context(table_id)
    try:
        values = validate_row(table, body.values, enums, rows)
    except RefValidationError as exc:
        return invalid(exc)
    return ref.add_row(table_id, RefRow(values=values))


@router.put("/tables/{table_id}/rows/{row_id}", response_model=RefRow)
def update_row(table_id: str, row_id: str, body: RowValues):
    ref, table, enums, rows = _row_context(table_id)
    if not any(r.id == row_id for r in rows):
        raise _not_found("row")
    try:
        values = validate_row(table, body.values, enums, [r for r in rows if r.id != row_id])
    except RefValidationError as exc:
        return invalid(exc)
    return ref.update_row(table_id, RefRow(id=row_id, values=values))


@router.delete("/tables/{table_id}/rows/{row_id}")
def delete_row(table_id: str, row_id: str) -> dict[str, str]:
    get_ref().delete_row(table_id, row_id)
    return {"status": "deleted"}
