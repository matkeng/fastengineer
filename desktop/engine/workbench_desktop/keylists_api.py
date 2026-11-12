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
    DISCIPLINES,
    EquipmentCode,
    EquipmentCodeList,
    InstrumentCode,
    InstrumentCodeList,
    PACKAGE_TYPES,
    PHASES,
    RATING_UNITS,
    EquipmentPackage,
    EquipmentPackageList,
    EquipmentType,
    LoadTypeList,
    PlantArea,
    PlantAreaList,
    check_code_list,
    check_equipment_packages,
    check_load_types,
    check_plant_areas,
    plant_area_depth,
)
from pathlib import Path

from workbench_core.keylists.cable_types import CableTypeList, check_cable_types, default_cable_types
from workbench_core.refdata import RefValidationError, name_key
from workbench_core.symbols.render import PdfError, page_count

from .refdata_api import invalid
from .storage import NotFound, get_keylists, get_loadlist

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
            "load_types": {"items": len(lists.load_types().items)}, "rating_units": RATING_UNITS, "phases": PHASES,
            "load_list": _load_list_counts(),
            "equipment_codes": {"items": len(lists.code_list("equipment-codes").items)},
            "instrument_codes": {"items": len(lists.code_list("instrument-codes").items)},
            "disciplines": [{"code": c, "name": n} for c, n in lists.disciplines().items()],  # the project's Disciplines enum
            "eel": {"items": len(lists.eel().items)},
            "plc": _plc_counts(lists.plc()),
            "cable_types": {"items": len(lists.cable_types().items)},
            "motors": {"items": len(lists.motors().items)},
            "drives": {"items": len(lists.drives().items)},
            "distribution_panels": {"items": len(lists.distribution_panels().panels)},
            "instrument_runsheet": {"items": len(lists.instrument_runsheet().rows)},
            "mel": {"items": _mel_count()},
            "drawing_list": {"items": len(lists.drawing_list().items)},
            "document_list": {"items": len(lists.document_list().items)},
            "enums": {"items": sum(len(getattr(lists.enums(), k))
                                   for k in ("disciplines", "drawing_types", "document_types", "drawing_statuses"))}}


def _mel_count() -> int:
    """Rows in the latest file of every MEL import (from what is stored: no file is read again)."""
    from .storage import get_store
    st = get_store()
    return sum((st.list_revisions(r["id"]) or [None])[0].num_rows for r in st.list_recipes()
               if r["target"] == "MEL" and r["revisions"])


def _refuse_runsheet(field: str, removed: dict[str, str], what: str) -> None:
    """Refuse to delete equipment types or plant areas that Instrument Runsheet rows refer to.
    `field`: equipment_type_id or plant_area_id; `removed`: id -> label."""
    counts: dict[str, int] = {}
    for r in get_keylists().instrument_runsheet().rows:
        if getattr(r, field) in removed:
            counts[getattr(r, field)] = counts.get(getattr(r, field), 0) + 1
    if counts:
        raise RefValidationError(f"These {what} are used in the Instrument Runsheet and can't be deleted: " + ", ".join(
            f"{removed[i]} ({n} row{'s' if n > 1 else ''})" for i, n in counts.items()) + ". Change those rows first.")


def _plc_counts(plc) -> dict[str, int]:
    from workbench_core.keylists.plc import cards
    return {"systems": len(plc.systems), "racks": sum(len(s.racks) for s in plc.systems), "cards": sum(1 for _ in cards(plc))}


def _load_list_counts() -> dict[str, int]:
    """From the remembered rows (the Load List brings them up to date when it is opened)."""
    rows = [r for r in get_loadlist().rows() if r.status == "active"]
    return {"rows": len(rows), "unallocated": sum(not (r.plant_area_id and r.load_type_id) for r in rows)}


def _refuse_eel(fields: tuple[str, ...], removed: dict[str, str], what: str) -> None:
    """Refuse to delete items the Electrical Equipment List refers to. `removed`: id -> label."""
    from .eel_api import eel_uses  # imported late: eel_api builds on the key lists
    in_use = eel_uses(fields, removed)
    if in_use:
        raise RefValidationError(f"These {what} are used in the Electrical Equipment List and can't be deleted: "
                                 f"{', '.join(in_use)}. Change those items first.")


def _refuse_plc(removed: dict[str, str]) -> None:
    """Refuse to delete plant areas that PLC racks are located in. `removed`: id -> tag."""
    counts: dict[str, int] = {}
    for s in get_keylists().plc().systems:
        for r in s.racks:
            if r.plant_area_id in removed:
                counts[r.plant_area_id] = counts.get(r.plant_area_id, 0) + 1
    if counts:
        raise RefValidationError("These plant areas have PLC racks in them and can't be deleted: " + ", ".join(
            f"{removed[i]} ({n} rack{'s' if n > 1 else ''})" for i, n in counts.items()) + ". Move those racks first.")


def _refuse_in_use(kind: str, removed: dict[str, str], what: str) -> None:
    """Refuse to delete items a person (or the Electrical Equipment List) allocated in the Load
    List. `removed`: id -> label."""
    _refuse_eel((f"{kind}_id",), removed, what)
    used = get_loadlist().used(kind)
    in_use = [f"{label} ({used[i]} row{'s' if used[i] > 1 else ''})" for i, label in removed.items() if i in used]
    if in_use:
        raise RefValidationError(f"These {what} are allocated in the Load List and can't be deleted: "
                                 f"{', '.join(in_use)}. Change those rows first.")


@router.get("/plant-areas", response_model=PlantAreaList)
def get_plant_areas() -> PlantAreaList:
    return get_keylists().plant_areas()


class PlantAreasUpdate(BaseModel):
    nodes: list[PlantArea]


@router.put("/plant-areas", response_model=PlantAreaList)
def update_plant_areas(body: PlantAreasUpdate):
    try:
        areas = check_plant_areas(PlantAreaList(nodes=body.nodes))
        kept = {n.id for n in areas.nodes}
        _refuse_in_use("plant_area", {n.id: n.tag for n in get_keylists().plant_areas().nodes if n.id not in kept},
                       "plant areas")
        _refuse_plc({n.id: n.tag for n in get_keylists().plant_areas().nodes if n.id not in kept})
        _refuse_runsheet("plant_area_id", {n.id: n.tag for n in get_keylists().plant_areas().nodes if n.id not in kept},
                         "plant areas")
        return get_keylists().save_plant_areas(areas)
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
        packages = check_equipment_packages(EquipmentPackageList(items=body.items, types=types), lists.master_columns().all())
        kept = {p.id for p in packages.items}
        _refuse_eel(("vendor_package_id", "supplied_by_id", "installed_by_id", "terminated_by_id"),
                    {p.id: p.number for p in lists.equipment_packages().items if p.id not in kept}, "packages")
        kept_types = {t.id for t in packages.types}
        _refuse_runsheet("equipment_type_id", {t.id: t.name for t in lists.equipment_packages().types if t.id not in kept_types},
                         "equipment types")
        return lists.save_equipment_packages(packages)
    except RefValidationError as exc:
        return invalid(exc)


@router.get("/load-types", response_model=LoadTypeList)
def get_load_types() -> LoadTypeList:
    return get_keylists().load_types()


class LoadTypesUpdate(BaseModel):
    items: list[dict]  # as typed in: check_load_types converts the numbers and names each problem


@router.get("/load-types/lists")
def load_type_lists() -> dict:
    """The deliverable lists a load type has rows for (with their columns), and the tags a row can use."""
    from workbench_core.keylists.instrument_runsheet import number_count
    from workbench_core.keylists.instrument_runsheet import tags as instrument_tags
    from workbench_core.keylists.loadgen import LISTS, ROW_SETTINGS, TAGS, TEMPLATE_LISTS
    from workbench_core.keylists.tag_paths import MODIFIERS, help_paths
    cols = get_keylists().master_columns()
    return {"lists": [{"key": k, "name": LISTS[k].deliverable_type, "columns": cols.of(k),
                       "settings": [{"name": n, "values": list(v)} for n, v in ROW_SETTINGS.get(k, {}).items()]}
                      for k in TEMPLATE_LISTS],
            "tags": [{"tag": f"<<{t}>>", "meaning": m} for t, m in TAGS],
            # what an equipment type's rows can use: the columns of the Instrument Runsheet
            # (with as many <<#n>> as the runsheet has number columns now; a higher one can be typed)
            "instrument_tags": [{"tag": t, "meaning": m}
                                for t, m in instrument_tags(number_count(get_keylists().instrument_runsheet()))],
            # dot notation: the linked records' fields a load's / a runsheet row's rows can reach, and the modifiers
            "paths": [{"tag": t, "meaning": m} for t, m in help_paths("load")],
            "instrument_paths": [{"tag": t, "meaning": m} for t, m in help_paths("runsheet")],
            "modifiers": [{"name": n, "meaning": m, "example": e, "args": a} for n, (a, m, e) in MODIFIERS.items()]}


@router.put("/load-types", response_model=LoadTypeList)
def update_load_types(body: LoadTypesUpdate):
    try:
        loads = check_load_types(body.items, get_keylists().master_columns().all())
        kept = {r.id for r in loads.items}
        _refuse_in_use("load_type", {r.id: r.code for r in get_keylists().load_types().items if r.id not in kept},
                       "load types")
        return get_keylists().save_load_types(loads)
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


# -- equipment codes and instrument codes ---------------------------------------------------

class CodeListUpdate(BaseModel):
    items: list[dict]  # as sent: check_code_list names each problem


def _code_list_routes(list_id: str, model, list_model, what: str) -> None:
    @router.get(f"/{list_id}", response_model=list_model, name=f"get_{list_id}")
    def get_codes():
        return get_keylists().code_list(list_id)

    @router.put(f"/{list_id}", response_model=list_model, name=f"update_{list_id}")
    def update_codes(body: CodeListUpdate):
        try:
            items = check_code_list(body.items, model, what, get_keylists().disciplines())
            if list_id == "equipment-codes":
                kept = {i.id for i in items}
                _refuse_eel(("equipment_code_id",), {c.id: c.code for c in get_keylists().code_list(list_id).items
                                                     if c.id not in kept}, "equipment codes")
            return get_keylists().save_code_list(list_id, items)
        except RefValidationError as exc:
            return invalid(exc)


_code_list_routes("equipment-codes", EquipmentCode, EquipmentCodeList, "equipment codes")
_code_list_routes("instrument-codes", InstrumentCode, InstrumentCodeList, "instrument codes")


# -- motor data --------------------------------------------------------------------------------

@router.get("/motors")
def get_motors():
    return get_keylists().motors()


@router.put("/motors")
def update_motors(body: CodeListUpdate):
    from workbench_core.keylists.motors import check_motors
    try:
        return get_keylists().save_motors(check_motors(body.items))
    except RefValidationError as exc:
        return invalid(exc)


@router.post("/motors/defaults")
def motor_defaults():
    """Add the WEG W22 motors that are missing (by part number); the rest is kept as it is."""
    from workbench_core.keylists.motors import default_motors
    lists = get_keylists()
    items = lists.motors().items
    have = {name_key(m.part_no) for m in items}
    missing = [m for m in default_motors() if name_key(m.part_no) not in have]
    if not missing:
        return lists.motors()
    return lists.save_motors(items + missing, note=f"{len(missing)} WEG W22 motor(s) added")


# -- drive data --------------------------------------------------------------------------------

@router.get("/drives")
def get_drives():
    return get_keylists().drives()


@router.put("/drives")
def update_drives(body: CodeListUpdate):
    from workbench_core.keylists.drives import check_drives
    try:
        return get_keylists().save_drives(check_drives(body.items))
    except RefValidationError as exc:
        return invalid(exc)


@router.post("/drives/defaults")
def drive_defaults():
    """Add the PowerFlex 755TS drives that are missing (by voltage and catalog number); the rest is kept."""
    from workbench_core.keylists.drives import default_drives
    lists = get_keylists()
    items = lists.drives().items
    have = {(name_key(d.cat_no), d.voltage) for d in items}
    missing = [d for d in default_drives() if (name_key(d.cat_no), d.voltage) not in have]
    if not missing:
        return lists.drives()
    return lists.save_drives(items + missing, note=f"{len(missing)} PowerFlex 755TS drive(s) added")


# -- cable types -------------------------------------------------------------------------------

@router.get("/cable-types", response_model=CableTypeList)
def get_cable_types() -> CableTypeList:
    return get_keylists().cable_types()


@router.put("/cable-types", response_model=CableTypeList)
def update_cable_types(body: CodeListUpdate):
    try:
        return get_keylists().save_cable_types(check_cable_types(body.items))
    except RefValidationError as exc:
        return invalid(exc)


@router.post("/cable-types/defaults", response_model=CableTypeList)
def cable_type_defaults() -> CableTypeList:
    """Add the default cable types that are missing (by code); the rest is kept as it is."""
    lists = get_keylists()
    items = lists.cable_types().items
    have = {name_key(c.code) for c in items}
    ids = {c.id for c in items}
    missing = [c if c.id not in ids else c.model_copy(update={"id": f"{c.id}x"})
               for c in default_cable_types() if name_key(c.code) not in have]
    if not missing:
        return lists.cable_types()
    return lists.save_cable_types(items + missing, note=f"{len(missing)} default cable type(s) added")
