# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""The PLC List (systems -> racks -> cards -> IO points) and the shared catalogue of card and
rack types. It replaces the PLC hardware register each generator used to have."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel

from workbench_core.generators.hardware import Catalogue, HardwareSummary, default_catalogue, summarise
from workbench_core.generators.models import Finding
from workbench_core.keylists.plc import (PlcList, as_hardware, cards, check_plc, normalise_points, read_workbook,
                                         write_workbook)
from workbench_core.refdata import RefValidationError, name_key

from .loadlist_api import Choice, _choices
from .refdata_api import invalid
from .storage import get_keylists

router = APIRouter(prefix="/api/plc", tags=["PLC list"])
MAX_UPLOAD = 50 * 1024 * 1024
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class PlcView(BaseModel):
    plc: PlcList
    catalogue: Catalogue
    errors: dict[str, str]  # field -> message (they block a save)
    findings: list[Finding]  # warnings
    summary: HardwareSummary
    plant_areas: list[Choice]


def _view(plc: PlcList, errors: dict[str, str] | None = None) -> PlcView:
    lists = get_keylists()
    cat = lists.catalogue()
    areas, _ = _choices()
    found, findings = check_plc(plc, cat, {a.id for a in areas})
    return PlcView(plc=plc, catalogue=cat, errors=(errors or {}) | found, findings=findings,
                   summary=summarise(as_hardware(plc), cat), plant_areas=areas)


def _checked(plc: PlcList) -> PlcList:
    """Points normalised to the card types; raises RefValidationError if anything blocks a save."""
    lists = get_keylists()
    plc, errors = normalise_points(plc, lists.catalogue())
    found, _ = check_plc(plc, lists.catalogue(), {n.id for n in lists.plant_areas().nodes})
    errors |= found
    if errors:
        raise RefValidationError(f"{len(errors)} problem(s) in the PLC List.", errors)
    return plc


@router.get("", response_model=PlcView)
def get_plc() -> PlcView:
    return _view(get_keylists().plc())


@router.put("", response_model=PlcView)
def save_plc(body: PlcList):
    try:
        return _view(get_keylists().save_plc(_checked(body)))
    except RefValidationError as exc:
        return invalid(exc)


@router.post("/check", response_model=PlcView)
def check_draft(body: PlcList) -> PlcView:
    """Points, errors, findings and totals for unsaved edits (nothing is saved)."""
    plc, errors = normalise_points(body, get_keylists().catalogue())
    return _view(plc, errors)


# -- the catalogue of card and rack types ------------------------------------------------------

def _check_catalogue(cat: Catalogue) -> None:
    ids = [t.id for t in cat.rack_types] + [t.id for t in cat.card_types]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        raise RefValidationError(f"Type ids used twice: {', '.join(dup)}", {"catalogue": "Duplicate ids"})
    if [t for t in cat.card_types if t.channels < 0] + [t for t in cat.rack_types if t.max_slots is not None and t.max_slots < 1]:
        raise RefValidationError("Channels can't be negative and a rack needs at least one slot.", {"catalogue": "Not valid"})
    plc = get_keylists().plc()
    racks = {r.rack_type_id for s in plc.systems for r in s.racks}
    used = {c.card_type_id for *_x, c in cards(plc)}
    gone = sorted((racks - {t.id for t in cat.rack_types}) | (used - {t.id for t in cat.card_types}))
    if gone:
        raise RefValidationError(f"{len(gone)} type(s) are used by racks or cards and can't be removed.",
                                 {"catalogue": "Types in use"})


@router.get("/catalogue", response_model=Catalogue)
def get_catalogue() -> Catalogue:
    return get_keylists().catalogue()


@router.put("/catalogue", response_model=Catalogue)
def save_catalogue(body: Catalogue):
    try:
        _check_catalogue(body)
    except RefValidationError as exc:
        return invalid(exc)
    return get_keylists().save_catalogue(body)


@router.post("/catalogue/defaults", response_model=Catalogue)
def catalogue_defaults() -> Catalogue:
    """Add any default types that are missing (existing types are kept)."""
    lists = get_keylists()
    cat = lists.catalogue()
    have = {t.id for t in cat.rack_types} | {t.id for t in cat.card_types}
    d = default_catalogue()
    cat.rack_types += [t for t in d.rack_types if t.id not in have]
    cat.card_types += [t for t in d.card_types if t.id not in have]
    return lists.save_catalogue(cat)


# -- workbook ----------------------------------------------------------------------------------

class ExportBody(BaseModel):
    path: str | None = None  # desktop: chosen in a Save As dialog


@router.post("/export")
def export_plc(body: ExportBody):
    """The PLC List as .xlsx: PLC cards, IO points, card types and rack types."""
    lists = get_keylists()
    data = write_workbook(lists.plc(), lists.catalogue(), {n.id: n.tag for n in lists.plant_areas().nodes})
    if body.path is None:
        return Response(data, media_type=XLSX, headers={"Content-Disposition": 'attachment; filename="PLC List.xlsx"'})
    target = Path(body.path)
    if target.suffix.lower() != ".xlsx":
        target = target.with_suffix(".xlsx")
    try:
        target.write_bytes(data)
    except OSError as exc:
        raise HTTPException(409, f"Could not write {target}: {exc.strerror or exc}. Is it open in another program?") from exc
    return {"path": str(target)}


class ImportPreview(BaseModel):
    systems: int
    racks: int
    cards: int
    tagged_points: int
    card_types: int
    rack_types: int
    notes: list[str]
    applied: bool = False


@router.post("/import", response_model=ImportPreview)
async def import_plc(request: Request, filename: str = Query(...), apply: bool = Query(False)):
    """Read a PLC List workbook (or a generator inputs workbook's PLC sheets). Without
    `apply` nothing is saved; with it the file replaces the PLC List and the types."""
    data = await request.body()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "The file is larger than 50 MB.")
    lists = get_keylists()
    areas = {name_key(n.tag): n.id for n in lists.plant_areas().nodes}
    try:
        res = await run_in_threadpool(read_workbook, data, lists.catalogue(), areas)
    except ValueError as exc:
        raise HTTPException(400, f"Could not read {Path(filename).name}: {exc}") from exc
    found, _ = check_plc(res.plc, res.catalogue, set(areas.values()))
    preview = ImportPreview(
        systems=len(res.plc.systems), racks=sum(len(s.racks) for s in res.plc.systems),
        cards=sum(1 for _ in cards(res.plc)), tagged_points=sum(1 for *_x, c in cards(res.plc) for p in c.points if p.tag),
        card_types=len(res.catalogue.card_types), rack_types=len(res.catalogue.rack_types), notes=res.notes)
    if found:
        return invalid(RefValidationError("The file has problems: " + "; ".join(sorted(set(found.values()))[:5]) + ".", found))
    if not apply:
        return preview
    lists.save_catalogue(res.catalogue)
    lists.save_plc(res.plc, note=f"Imported from {Path(filename).name}")
    return preview.model_copy(update={"applied": True})
