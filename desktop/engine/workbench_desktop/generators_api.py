# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Deliverable generators. The app has two built-in types (see /types): Power, which makes its
rows from the Project Load List and the load types, and Instrument, which makes its rows from
the Instrument Runsheet and the equipment types. Both fill the Project Master lists.

Generators made from a generator workbook belong to earlier versions: the app no longer offers
the import, but the ones a project has can still be edited, checked, built and exported here.
(The import endpoint stays for the command line and the tests.)"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from workbench_core.generators import BuildError, build, check
from workbench_core.generators.check import CheckResult
from workbench_core.generators.bulk import BulkPreview, Inputs, apply_inputs, read_inputs, write_inputs
from workbench_core.generators.editable import BuildInfo, BuildRecord, GenRecord, GenSummary, input_hash, merge, split
from workbench_core.generators.expand import discover_tags
from workbench_core.generators.hardware import Catalogue, Hardware, HardwareSummary, ScheduleRow, schedule, summarise
from workbench_core.generators.models import Finding, Generator, RefTable
from workbench_core.generators.preview import PreviewResult, preview
from workbench_core.generators.xlsx_export import csv_bytes, export_name, xlsx_bytes
from workbench_core.generators.xlsx_import import ImportReport, import_workbook

from .storage import NotFound, get_generators

router = APIRouter(prefix="/api/generators", tags=["generators"])
MAX_UPLOAD = 100 * 1024 * 1024
MEDIA = {"csv": "text/csv", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}


def _record(rid: str) -> GenRecord:
    try:
        return get_generators().get(rid)
    except NotFound as exc:
        raise HTTPException(404, "Generator not found.") from exc


def _build_record(bid: str) -> BuildRecord:
    try:
        return get_generators().get_build(bid)
    except NotFound as exc:
        raise HTTPException(404, "Build not found.") from exc


def _json_only(request: Request) -> None:
    # JSON only: forces a CORS preflight, so a cross-site page can't trigger a file write.
    if not request.headers.get("content-type", "").startswith("application/json"):
        raise HTTPException(415, "Expected application/json")


def _invalid(message: str, field: str = "generator") -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": message, "fields": {field: message}})


def _full(rec: GenRecord, draft: Generator | None = None) -> Generator:
    """The generator to run: the draft (unsaved edits) when given, with the stored tables."""
    return merge(draft or rec.generator, get_generators().tables(rec.id))


# -- generators ----------------------------------------------------------------

class ImportResponse(BaseModel):
    record: GenRecord
    report: ImportReport


@router.post("/import", response_model=ImportResponse)
async def import_file(request: Request, filename: str = Query(...), name: str | None = Query(None)):
    data = await request.body()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "The file is larger than 100 MB.")
    if not data:
        raise HTTPException(400, "The file is empty.")
    try:
        res = await run_in_threadpool(import_workbook, data, None, filename)
    except (ValueError, BuildError, KeyError) as exc:
        raise HTTPException(400, f"Could not import {filename}: {exc}") from exc
    gen, tables = split(res.generator)
    title = name or gen.config.doc_title or Path(filename).stem
    rec = get_generators().create(title, gen.id, filename, gen, tables, res.report)
    return ImportResponse(record=rec, report=res.report)


# -- the built-in generators -----------------------------------------------------------------
# Generators are not made from a workbook any more. There are two, built into the app, and both
# write to the same four Project Master lists (see master_api): "power" (the Project Load List
# through the load types' rows) and "instrument" (the Instrument Runsheet through the equipment
# types' rows).

class GeneratorList(BaseModel):
    key: str
    type: str  # the deliverable type made from the master list
    master: str  # the project master list it writes to
    rows: int  # rows this generator adds to it now
    master_rows: int  # rows the master list has in all (both generators)
    deliverables: int  # deliverables made from the master list


class GeneratorType(BaseModel):
    id: Literal["power", "instrument"]
    name: str
    available: bool
    description: str
    # Power: loads of the Load List and load types. Instrument: runsheet rows and equipment types that have rows.
    runs: int = 0
    templates: int = 0
    missing: list[str] = []  # Power: tags of the loads with no load type, which add nothing yet
    unconfirmed: int = 0  # Instrument: runsheet rows not confirmed (they generate, flagged)
    lists: list[GeneratorList] = []


@router.get("/types", response_model=list[GeneratorType])
def generator_types() -> list[GeneratorType]:
    """The two generators, with what each adds to the four Project Master lists right now."""
    from workbench_core.keylists.loadgen import LISTS
    from workbench_core.keylists.master import INSTRUMENT, MASTER_LISTS, MASTER_NAMES, POWER, generator_counts

    from .master_api import inputs, master_of
    from .storage import get_deliverables

    src = inputs()
    used: dict[str, int] = {}
    for d in get_deliverables().list():
        if d.source == "project":
            used[d.type] = used.get(d.type, 0) + 1
    rows: dict[str, list[GeneratorList]] = {POWER: [], INSTRUMENT: []}
    missing: list[str] = []
    for key in MASTER_LISTS:
        result, _, missing = master_of(key, src)
        counts = generator_counts(result)
        for who in (POWER, INSTRUMENT):
            rows[who].append(GeneratorList(key=key, type=LISTS[key].deliverable_type, master=MASTER_NAMES[key], rows=counts[who],
                                           master_rows=len(result.rows), deliverables=used.get(LISTS[key].deliverable_type, 0)))
    sheet = src.runsheet.rows  # type: ignore[attr-defined]
    return [
        GeneratorType(id="power", name="Power", available=True,
                      description="Every load of the Project Load List adds the rows its load type has for each list.",
                      runs=sum(1 for r in src.loads if r.status == "active"), templates=len(src.load_types), missing=missing,
                      lists=rows[POWER]),
        GeneratorType(id="instrument", name="Instrument", available=True,
                      description="Every row of the Instrument Runsheet adds the rows its equipment type has for each list.",
                      runs=len(sheet), templates=sum(1 for t in src.equipment_types.values() if any(t.rows.values())),
                      unconfirmed=sum(1 for r in sheet if not r.confirmed), lists=rows[INSTRUMENT])]


@router.get("", response_model=list[GenSummary])
def list_generators():
    return get_generators().list()


@router.get("/{rid}", response_model=GenRecord)
def get_generator(rid: str):
    return _record(rid)


class SaveBody(BaseModel):
    name: str
    generator: Generator


@router.put("/{rid}", response_model=GenRecord)
def save_generator(rid: str, body: SaveBody):
    _record(rid)
    if not body.name.strip():
        return _invalid("Give the generator a name.", "name")
    try:
        discover_tags(body.generator)
    except BuildError as exc:
        return _invalid(str(exc), "runsheet")
    return get_generators().save(rid, body.name.strip(), body.generator)


@router.delete("/{rid}")
def delete_generator(rid: str):
    _record(rid)
    from .storage import get_deliverables
    used = get_deliverables().using(rid)
    if used:
        return _invalid(f"This generator feeds the deliverable(s) {', '.join(used)} and can't be deleted. "
                        "Point them at another generator, or delete them, first.")
    get_generators().delete(rid)
    return {"ok": True}


@router.get("/{rid}/tables/{name}", response_model=RefTable)
def get_table(rid: str, name: str):
    _record(rid)
    t = get_generators().tables(rid).get(name)
    if t is None:
        raise HTTPException(404, "Table not found.")
    return t


# -- check, preview -----------------------------------------------------------

class DraftBody(BaseModel):
    draft: Generator | None = None


@router.post("/{rid}/check", response_model=CheckResult)
async def check_generator(rid: str, body: DraftBody | None = None):
    rec = _record(rid)
    return await run_in_threadpool(check, _full(rec, body.draft if body else None))


class PreviewBody(BaseModel):
    run_row_id: str
    template_id: str | None = None
    draft: Generator | None = None


@router.post("/{rid}/preview", response_model=PreviewResult)
def preview_run(rid: str, body: PreviewBody):
    rec = _record(rid)
    return preview(_full(rec, body.draft), body.run_row_id, body.template_id)


# -- builds -------------------------------------------------------------------

class BuildBody(BaseModel):
    run_from: float | None = None
    run_up_to: float | None = None
    use_config_range: bool = True  # False: build every run (run_from / run_up_to still apply when given)


@router.post("/{rid}/builds", response_model=BuildInfo)
async def start_build(rid: str, body: BuildBody | None = None):
    """Builds run in the request: the largest generator builds in well under a second."""
    body = body or BuildBody()
    rec = _record(rid)
    store = get_generators()
    tables = store.tables(rid)
    gen = merge(rec.generator, tables)
    prev = store.latest_build(rid)
    try:
        res = await run_in_threadpool(build, gen, prev.result if prev else None, body.run_from, body.run_up_to,
                                      body.use_config_range)
    except BuildError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc), "fields": {"build": str(exc)},
                                                      "stage": exc.stage, "run": exc.run, "row": exc.row})
    cfg = gen.config
    rf = body.run_from if body.run_from is not None or not body.use_config_range else cfg.run_from
    ru = body.run_up_to if body.run_up_to is not None or not body.use_config_range else cfg.run_up_to
    ch = res.changes
    info = BuildInfo(id=uuid.uuid4().hex, generator_id=rid, seq=0, created_at=datetime.now(timezone.utc),
                     input_hash=input_hash(rec.generator, tables, rf, ru), engine_version=res.engine_version,
                     run_from=rf, run_up_to=ru, stats=res.stats, warnings=res.warnings,
                     unresolved_count=res.unresolved_count, unresolved_tokens=res.unresolved_tokens,
                     added=ch.added if ch else None, removed=ch.removed if ch else None,
                     changed=ch.changed if ch else None)
    return store.add_build(info, res)


@router.get("/{rid}/builds", response_model=list[BuildInfo])
def list_builds(rid: str):
    _record(rid)
    return get_generators().list_builds(rid)


@router.get("/builds/{bid}", response_model=BuildRecord)
def get_build(bid: str):
    return _build_record(bid)


@router.delete("/builds/{bid}")
def delete_build(bid: str) -> dict[str, bool]:
    _build_record(bid)
    get_generators().delete_build(bid)
    return {"ok": True}


class ExportBody(BaseModel):
    format: Literal["xlsx", "csv"] = "xlsx"
    path: str | None = None  # desktop: chosen in a Save As dialog


@router.post("/builds/{bid}/export")
def export_build(bid: str, body: ExportBody, request: Request):
    _json_only(request)
    b = _build_record(bid)
    rec = _record(b.info.generator_id)
    cfg = rec.generator.config
    data = (xlsx_bytes(b.result, cfg, f"{b.info.seq}") if body.format == "xlsx"
            else csv_bytes(b.result, cfg.date_format))
    if body.path is None:
        name = export_name(cfg, rec.name, b.info.created_at, f".{body.format}")
        return Response(data, media_type=MEDIA[body.format],
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})
    target = Path(body.path)
    if target.suffix.lower() != f".{body.format}":
        target = target.with_suffix(f".{body.format}")
    try:
        target.write_bytes(data)
    except OSError as exc:
        raise HTTPException(409, f"Could not write {target}: {exc.strerror or exc}. Is it open in another program?") from exc
    return {"path": str(target)}


@router.get("/builds/{bid}/name")
def export_file_name(bid: str, format: Literal["xlsx", "csv"] = "xlsx") -> dict[str, str]:
    """Suggested file name for the Save As dialog."""
    b = _build_record(bid)
    rec = _record(b.info.generator_id)
    return {"name": export_name(rec.generator.config, rec.name, b.info.created_at, f".{format}")}


# -- PLC hardware: read-only, from the project's PLC List -------------------------------------

class HardwareView(BaseModel):
    hardware: Hardware
    catalogue: Catalogue
    findings: list[Finding]
    summary: HardwareSummary
    schedule: list[ScheduleRow]


@router.get("/{rid}/hardware", response_model=HardwareView)
def get_hardware(rid: str):
    """The PLC List's cards and channels against this generator's latest IO list build (the
    register itself is edited in Project lists > PLC List)."""
    _record(rid)
    from workbench_core.keylists.plc import as_hardware

    from .storage import get_keylists
    lists = get_keylists()
    hw, cat = as_hardware(lists.plc()), lists.catalogue()
    latest = get_generators().latest_build(rid)
    return HardwareView(hardware=hw, catalogue=cat, findings=[], summary=summarise(hw, cat, latest.result if latest else None),
                        schedule=schedule(hw, cat))


# -- bulk editing in Excel: every input table in one workbook -------------------------------

def _inputs(rid: str) -> Inputs:
    store = get_generators()
    rec = _record(rid)
    return Inputs(generator=merge(rec.generator, store.tables(rid)))


@router.post("/{rid}/inputs/export")
def export_inputs(rid: str, body: ExportBody, request: Request):
    """All input tables (runsheet, templates, parents, derived tags, routes, prefixes, lookup
    tables) in one .xlsx for editing outside the app. (PLC cards are in the PLC List's workbook.)"""
    _json_only(request)
    rec = _record(rid)
    data = write_inputs(_inputs(rid), rec.name)
    name = f"{rec.name} inputs.xlsx".replace("/", "_")
    if body.path is None:
        return Response(data, media_type=MEDIA["xlsx"], headers={"Content-Disposition": f'attachment; filename="{name}"'})
    target = Path(body.path)
    if target.suffix.lower() != ".xlsx":
        target = target.with_suffix(".xlsx")
    try:
        target.write_bytes(data)
    except OSError as exc:
        raise HTTPException(409, f"Could not write {target}: {exc.strerror or exc}. Is it open in another program?") from exc
    return {"path": str(target)}


class InputsImport(BaseModel):
    preview: BulkPreview
    applied: list[str] = []
    record: GenRecord | None = None


@router.post("/{rid}/inputs/import", response_model=InputsImport)
async def import_inputs(rid: str, request: Request, filename: str = Query(...), apply: str = Query("")):
    """Without `apply`: a per-sheet preview of what the file would change (nothing is saved).
    With `apply=runsheet,templates,...`: those sheets are saved (sheets with errors never are)."""
    data = await request.body()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "The file is larger than 100 MB.")
    current = _inputs(rid)
    try:
        preview, parsed = await run_in_threadpool(read_inputs, data, current)
    except ValueError as exc:
        raise HTTPException(400, f"Could not read {filename}: {exc}") from exc
    chosen = [t for t in (x.strip() for x in apply.split(",")) if t]
    if not chosen:
        return InputsImport(preview=preview)
    bad = [t for t in chosen if t not in parsed]
    if bad:
        return _invalid(f"These sheets can't be applied (missing or with errors): {', '.join(bad)}", "apply")
    new = apply_inputs(current, parsed, chosen)
    try:
        discover_tags(new.generator)
    except BuildError as exc:
        return _invalid(f"RunSheet: {exc}", "runsheet")
    store = get_generators()
    gen, tables = split(new.generator)
    rec = _record(rid)
    store.apply_import(
        rid, rec.name, gen,
        tables=tables if any(t.startswith("table:") for t in chosen) else None)
    return InputsImport(preview=preview, applied=chosen, record=_record(rid))
