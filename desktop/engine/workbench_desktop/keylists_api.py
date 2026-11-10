# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Key lists: the built-in lists of a project: Plant Areas (a tree) and Equipment Packages."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel

from workbench_core.keylists import (
    AREA_TYPES,
    PACKAGE_TYPES,
    PHASES,
    RATING_UNITS,
    EquipmentPackage,
    EquipmentPackageList,
    EquipmentType,
    LoadTypeList,
    PlantArea,
    PlantAreaList,
    check_equipment_packages,
    check_load_types,
    check_plant_areas,
    plant_area_depth,
)
from pathlib import Path

from workbench_core.refdata import RefValidationError
from workbench_core.symbols.render import PdfError, page_count

from .refdata_api import invalid
from .storage import NotFound, get_keylists

router = APIRouter(prefix="/api/keylists", tags=["key lists"])

MAX_PDF = 50 * 1024 * 1024


@router.get("")
def overview() -> dict:
    lists = get_keylists()
    areas = lists.plant_areas()
    packages = lists.equipment_packages()
    return {"plant_areas": {"items": len(areas.nodes), "depth": plant_area_depth(areas)}, "area_types": AREA_TYPES,
            "equipment_packages": {"items": len(packages.items), "types": len(packages.types)},
            "package_types": PACKAGE_TYPES,
            "load_types": {"items": len(lists.load_types().items)}, "rating_units": RATING_UNITS, "phases": PHASES}


@router.get("/plant-areas", response_model=PlantAreaList)
def get_plant_areas() -> PlantAreaList:
    return get_keylists().plant_areas()


class PlantAreasUpdate(BaseModel):
    nodes: list[PlantArea]


@router.put("/plant-areas", response_model=PlantAreaList)
def update_plant_areas(body: PlantAreasUpdate):
    try:
        return get_keylists().save_plant_areas(check_plant_areas(PlantAreaList(nodes=body.nodes)))
    except RefValidationError as exc:
        return invalid(exc)


@router.get("/equipment-packages", response_model=EquipmentPackageList)
def get_equipment_packages() -> EquipmentPackageList:
    return get_keylists().equipment_packages()


class EquipmentPackagesUpdate(BaseModel):
    items: list[EquipmentPackage]
    types: list[EquipmentType] | None = None  # left out: the equipment types stay as they are


@router.put("/equipment-packages", response_model=EquipmentPackageList)
def update_equipment_packages(body: EquipmentPackagesUpdate):
    lists = get_keylists()
    types = lists.equipment_packages().types if body.types is None else body.types
    try:
        return lists.save_equipment_packages(check_equipment_packages(EquipmentPackageList(items=body.items, types=types)))
    except RefValidationError as exc:
        return invalid(exc)


@router.get("/load-types", response_model=LoadTypeList)
def get_load_types() -> LoadTypeList:
    return get_keylists().load_types()


class LoadTypesUpdate(BaseModel):
    items: list[dict]  # as typed in: check_load_types converts the numbers and names each problem


@router.put("/load-types", response_model=LoadTypeList)
def update_load_types(body: LoadTypesUpdate):
    try:
        return get_keylists().save_load_types(check_load_types(body.items))
    except RefValidationError as exc:
        return invalid(exc)


# -- the PDF attached to a load type ----------------------------------------------------

def _file_name(name: str) -> str:
    """Just the file's name, whichever system the path came from."""
    return Path(name.replace("\\", "/")).name.strip() or "attachment.pdf"


def _no_load_type() -> HTTPException:
    return HTTPException(404, "That load type no longer exists. Open the list again.")


@router.put("/load-types/{load_id}/pdf", response_model=LoadTypeList)
async def attach_load_type_pdf(load_id: str, request: Request, filename: str = Query(...)) -> LoadTypeList:
    """Attach a PDF (the request body) to a load type, replacing the one it had."""
    data = await request.body()
    if len(data) > MAX_PDF:
        raise HTTPException(413, "The file is larger than 50 MB.")
    try:
        pages = await run_in_threadpool(page_count, data)
    except PdfError as exc:
        raise HTTPException(400, str(exc)) from exc
    if pages == 0:
        raise HTTPException(400, "The PDF has no pages.")
    try:
        return get_keylists().attach_load_type_pdf(load_id, data, _file_name(filename), pages)
    except NotFound as exc:
        raise _no_load_type() from exc


@router.get("/load-types/{load_id}/pdf")
def get_load_type_pdf(load_id: str) -> FileResponse:
    lists = get_keylists()
    row = next((r for r in lists.load_types().items if r.id == load_id), None)
    try:
        path = lists.load_type_pdf(load_id)
    except NotFound as exc:
        raise _no_load_type() from exc
    if row is None or row.pdf is None or not path.exists():
        raise HTTPException(404, "This load type has no PDF.")
    return FileResponse(path, media_type="application/pdf", filename=row.pdf.file_name, content_disposition_type="inline")


@router.delete("/load-types/{load_id}/pdf", response_model=LoadTypeList)
def remove_load_type_pdf(load_id: str) -> LoadTypeList:
    try:
        return get_keylists().remove_load_type_pdf(load_id)
    except NotFound as exc:
        raise _no_load_type() from exc
