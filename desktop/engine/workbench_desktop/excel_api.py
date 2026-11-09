"""Excel query endpoints: a thin HTTP layer over workbench_core.excel."""

from __future__ import annotations

import threading
import uuid
from collections import OrderedDict

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from workbench_core.excel import (
    ColumnsResult,
    CompareOptions,
    CompareResult,
    ExcelError,
    ExtractResult,
    PreviewResult,
    Workbook,
    WorkbookSummary,
    compare_tables,
)

router = APIRouter(prefix="/api/excel", tags=["excel"])

MAX_UPLOAD_BYTES = 200 * 1024 * 1024
MAX_OPEN_WORKBOOKS = 5


class _Store:
    """Keeps the last few loaded workbooks in memory between wizard steps."""

    def __init__(self) -> None:
        self._items: OrderedDict[str, Workbook] = OrderedDict()
        self._lock = threading.Lock()

    def add(self, wb: Workbook) -> None:
        with self._lock:
            self._items[wb.id] = wb
            while len(self._items) > MAX_OPEN_WORKBOOKS:
                self._items.popitem(last=False)

    def get(self, workbook_id: str) -> Workbook:
        with self._lock:
            wb = self._items.get(workbook_id)
            if wb is None:
                raise HTTPException(404, "Workbook is no longer open. Please load it again.")
            self._items.move_to_end(workbook_id)
            return wb

    def remove(self, workbook_id: str) -> None:
        with self._lock:
            self._items.pop(workbook_id, None)


store = _Store()


def _bad_request(exc: ExcelError) -> HTTPException:
    return HTTPException(400, str(exc))


@router.post("/workbooks", response_model=WorkbookSummary)
async def open_workbook(request: Request, filename: str = Query(..., min_length=1)) -> WorkbookSummary:
    """Upload a workbook as the raw request body (no multipart needed)."""
    data = await request.body()
    if not data:
        raise HTTPException(400, "The file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "The file is larger than 200 MB.")
    try:
        wb = await run_in_threadpool(Workbook, data, filename, uuid.uuid4().hex)
    except ExcelError as exc:
        raise _bad_request(exc) from exc
    store.add(wb)
    return wb.summary()


@router.get("/workbooks/{workbook_id}/preview", response_model=PreviewResult)
def preview(workbook_id: str, source: str, rows: int = Query(60, ge=5, le=500)) -> PreviewResult:
    try:
        return store.get(workbook_id).preview(source, max_rows=rows)
    except ExcelError as exc:
        raise _bad_request(exc) from exc


@router.get("/workbooks/{workbook_id}/columns", response_model=ColumnsResult)
def columns(workbook_id: str, source: str, header_row: int = Query(..., ge=1),
            header_rows: int = Query(1, ge=1, le=4)) -> ColumnsResult:
    try:
        return store.get(workbook_id).columns(source, header_row, header_rows)
    except ExcelError as exc:
        raise _bad_request(exc) from exc


class ExtractRequest(BaseModel):
    source: str
    header_row: int
    header_rows: int = 1
    key_column: int
    skip_blank_keys: bool = True


@router.post("/workbooks/{workbook_id}/extract", response_model=ExtractResult)
def extract(workbook_id: str, req: ExtractRequest) -> ExtractResult:
    try:
        return store.get(workbook_id).extract(
            req.source, req.header_row, req.key_column,
            header_rows=req.header_rows, skip_blank_keys=req.skip_blank_keys,
        )
    except ExcelError as exc:
        raise _bad_request(exc) from exc


@router.delete("/workbooks/{workbook_id}")
def close_workbook(workbook_id: str) -> dict[str, str]:
    store.remove(workbook_id)
    return {"status": "closed"}


class TableSpec(ExtractRequest):
    """One side of a comparison: the same choices as the extract step."""

    workbook_id: str


class CompareRequest(BaseModel):
    a: TableSpec  # old / base table
    b: TableSpec  # new / revised table
    options: CompareOptions = CompareOptions()


def _extract(spec: TableSpec) -> tuple[str, ExtractResult]:
    wb = store.get(spec.workbook_id)
    result = wb.extract(spec.source, spec.header_row, spec.key_column,
                        header_rows=spec.header_rows, skip_blank_keys=spec.skip_blank_keys)
    return f"{wb.filename} · {result.source.name}", result


@router.post("/compare", response_model=CompareResult)
def compare(req: CompareRequest) -> CompareResult:
    try:
        a_label, a = _extract(req.a)
        b_label, b = _extract(req.b)
    except ExcelError as exc:
        raise _bad_request(exc) from exc
    return compare_tables(a, b, req.options, a_label=a_label, b_label=b_label)
