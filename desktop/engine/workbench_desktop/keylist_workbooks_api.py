# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Every project list as an Excel workbook: export it, and import it back (see
workbench_core.keylists.workbooks). An import is read and checked first (a preview, nothing
saved); with `apply` it then goes through the list's own save, so every rule of the app holds
for a file too. (The PLC List has its own workbook, in plc_api.)"""

from __future__ import annotations

import json
import re
from typing import Literal
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from workbench_core.keylists import (EEL_SOURCE, EquipmentCode, EquipmentPackageList, InstrumentCode, PlantAreaList,
                                     check_code_list, check_equipment_packages, check_load_types, check_plant_areas)
from workbench_core.keylists import workbooks as wbk
from workbench_core.keylists.loadlist import load_type_names
from workbench_core.keylists.cable_types import check_cable_types
from workbench_core.keylists.distribution_panels import check_panels
from workbench_core.keylists.drawing_list import REGISTERS
from workbench_core.refdata import RefValidationError, name_key

from .exporting import save_to
from .uploads import read_upload
from . import distribution_panels_api, drawing_list_api, eel_api, instrument_runsheet_api, keylists_api, loadlist_api
from .storage import NotFound, get_keylists, get_loadlist

router = APIRouter(prefix="/api/list-workbooks", tags=["project list workbooks"])
MAX_UPLOAD = 50 * 1024 * 1024
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
#: list id -> (its name, what its items are called)
LISTS = {"plant-areas": ("Plant Areas", "plant area"), "equipment-packages": ("Equipment Packages", "package"),
         "load-types": ("Load Types", "load type"), "equipment-codes": ("Equipment Codes", "equipment code"),
         "instrument-codes": ("Instrument Codes", "instrument code"), "cable-types": ("Cable Types", "cable type"), "motors": ("Motor Data", "motor"), "drives": ("Drive Data", "drive"),
         "starters": ("Starter Coordination", "starter row"), "load-factors": ("Load Factors", "load factor row"),
         "instrument-types": ("Instrument Types", "instrument type"),
         "eel": ("Electrical Equipment List", "item"), "load-list": ("Load List", "row"),
         "distribution-panels": ("Distribution Panels", "panel"), "instrument-runsheet": ("Instrument Runsheet", "row"),
         "mel": ("MEL", "row"), "drawing-list": ("Drawing List", "drawing"), "document-list": ("Document List", "document"),
         "pid-symbols": ("PID Symbols", "symbol")}
#: Lists that are only read here: they can be exported, not imported or reset.
READ_ONLY = ("mel", "pid-symbols")


def _known(list_id: str) -> str:
    if list_id not in LISTS:
        raise HTTPException(404, "There is no project list with that name.")
    return LISTS[list_id][0]


def _eel_names() -> wbk.EelNames:
    lists = get_keylists()
    panels = [r for r in get_loadlist().rows() if r.recipe_id != EEL_SOURCE and r.status == "active" and r.is_panel]
    return wbk.EelNames(
        equipment_codes=[(c.id, c.code) for c in lists.code_list("equipment-codes").items],
        plant_areas=[(n.id, n.tag) for n in lists.plant_areas().nodes],
        packages=[(p.id, p.number) for p in lists.equipment_packages().items],
        load_types=load_type_names(lists.load_types().items), import_panels=[(r.ref(), r.tag()) for r in panels])


def _sheets(list_id: str) -> wbk.Sheets:
    lists = get_keylists()
    if list_id == "plant-areas":
        return wbk.export_plant_areas(lists.plant_areas())
    if list_id == "equipment-packages":
        return wbk.export_equipment_packages(lists.equipment_packages(), lists.master_columns().all())
    if list_id == "load-types":
        return wbk.export_load_types(lists.load_types(), lists.master_columns().all())
    if list_id in wbk.CODE_HEADS:
        return wbk.export_code_list(list_id, lists.code_list(list_id).items)
    if list_id == "cable-types":
        return wbk.export_cable_types(lists.cable_types().items)
    if list_id == "motors":
        return wbk.export_motors(lists.motors().items)
    if list_id == "drives":
        return wbk.export_drives(lists.drives().items)
    if list_id == "starters":
        return wbk.export_starters(lists.starters())
    if list_id == "load-factors":
        return wbk.export_load_factors(lists.load_factors().items)
    if list_id == "instrument-types":
        return wbk.export_instrument_types(lists.instrument_types().items)
    if list_id == "eel":
        return wbk.export_eel(lists.eel(), _eel_names())
    if list_id in REGISTERS:
        return wbk.export_register(REGISTERS[list_id], drawing_list_api.view_of(REGISTERS[list_id]).items)
    if list_id == "instrument-runsheet":
        return wbk.export_instrument_runsheet(instrument_runsheet_api.get_runsheet().rows)
    if list_id == "pid-symbols":
        from .pid_symbols_api import pid_symbols
        pid = pid_symbols()
        return wbk.export_pid_symbols(pid.fields, pid.rows)
    if list_id == "mel":
        mel = loadlist_api.mel_list()
        return wbk.export_mel(mel.headers, mel.rows)
    rows = loadlist_api.current_rows()[0]
    if list_id == "load-list":
        used = {k for r in rows for k, v in r.values.items() if v not in (None, "")}
        lf = lists.load_fields()
        return wbk.export_load_list(rows, {n.id: n.tag for n in lists.plant_areas().nodes},
                                    dict(load_type_names(lists.load_types().items)), [f for f in lf.keys() if f in used], lf.labels())
    return wbk.export_distribution_panels(lists.distribution_panels(), {r.ref(): r for r in rows})


class ExportBody(BaseModel):
    path: str | None = None  # desktop: chosen in a Save As dialog


# -- one load type's or equipment type's rows ----------------------------------------------------
# (before the /{list_id}/... routes, which would take "type-rows" for a list)

class TypeRowsBody(BaseModel):
    name: str  # the load type's code or the equipment type's name: the file is called after it
    kind: Literal["load", "equipment"]
    rows: dict[str, list[dict[str, str]]]  # as they are in the editor (saved or not)
    components: list[dict] = []  # a load type's component tables, as they are in the editor
    path: str | None = None  # desktop: chosen in a Save As dialog


def _write(data: bytes, path: str | None, name: str):
    if path is None:
        return Response(data, media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'})
    return save_to(path, data, ".xlsx")


@router.post("/type-rows/export")
def export_type_rows(body: TypeRowsBody):
    """One type's rows as a workbook: a sheet per list, and a Tags sheet of what a cell can use."""
    from workbench_core.keylists.instrument_runsheet import number_count
    from workbench_core.keylists.instrument_runsheet import tags as instrument_tags
    from workbench_core.keylists.loadgen import TAGS
    from workbench_core.keylists.tag_paths import MODIFIERS, help_paths

    lists = get_keylists()
    if body.kind == "load":
        tags = [(f"<<{t}>>", m) for t, m in TAGS]
        paths = help_paths("load")
    else:
        tags = list(instrument_tags(number_count(lists.instrument_runsheet())))
        paths = help_paths("runsheet")
    from workbench_core.keylists.models import ComponentTable

    tables = [ComponentTable.model_validate(t) for t in body.components] if body.kind == "load" else []
    sheets = wbk.export_type_rows(body.rows, lists.master_columns().all(), tags, paths,
                                  [(e, m) for _, (_, m, e) in MODIFIERS.items()], tables)
    name = re.sub(r'[\\/:*?"<>|]+', "_", body.name.strip() or "type") + " rows"
    return _write(wbk.write_sheets(sheets), body.path, name)


class TypeRowsRead(BaseModel):
    rows: dict[str, list[dict[str, str]]]  # list key -> rows, for the lists whose sheet is in the file
    counts: dict[str, int]  # list name -> rows
    notes: list[str]
    components: list[dict] | None = None  # a load type's component tables, when the file has "Table …" sheets


@router.post("/type-rows/import", response_model=TypeRowsRead)
async def import_type_rows(request: Request, kind: Literal["load", "equipment"] = Query(...), filename: str = Query(...)):
    """Read a workbook of one type's rows (as exported). Nothing is saved: the editor puts the
    rows in its form, saved with the form."""
    from workbench_core.keylists.loadgen import LISTS as OUTPUT_LISTS
    from workbench_core.keylists.validate import _template_rows

    data = await read_upload(request, MAX_UPLOAD)
    columns = get_keylists().master_columns().all()
    try:
        parsed = await run_in_threadpool(lambda: wbk.import_type_rows(wbk.read_sheets(data), columns))
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"detail": f"Could not read {Path(filename).name}: {exc}", "fields": {}})
    errors: dict[str, str] = {}
    rows = _template_rows(parsed.payload, "rows", errors, "load types" if kind == "load" else "equipment types", columns)
    tables = None
    if kind == "load":
        from workbench_core.keylists.validate import _components
        try:
            raw = await run_in_threadpool(wbk.read_component_tables, data)
        except ValueError as exc:
            return JSONResponse(status_code=422, content={"detail": f"Could not read {Path(filename).name}: {exc}", "fields": {}})
        if raw is not None:
            tables = [t.model_dump() for t in _components(raw, "tables", errors)]
    if errors:
        return JSONResponse(status_code=422, content={"detail": _problems(errors, {}, f"{Path(filename).name} has problems:"),
                                                      "fields": {}})
    rows = {k: rows.get(k, []) for k in parsed.payload}  # a sheet with no rows empties that list
    counts = {OUTPUT_LISTS[k].deliverable_type: len(v) for k, v in rows.items()}
    counts |= {f"Component table {t['name']}": len(t["rows"]) for t in tables or []}
    return TypeRowsRead(rows=rows, counts=counts, notes=parsed.notes, components=tables)


@router.post("/{list_id}/export")
def export_list(list_id: str, body: ExportBody):
    name = _known(list_id)
    data = wbk.write_sheets(_sheets(list_id))
    if body.path is None:
        return Response(data, media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{name}.xlsx"'})
    return save_to(body.path, data, ".xlsx")


class ImportPreview(BaseModel):
    summary: str  # what the file holds, against the list as it is
    notes: list[str]
    applied: bool = False


def _parse(list_id: str, data: bytes) -> tuple[wbk.Parsed, list[str]]:
    """What the file says, and the names of the list's items as they are now."""
    lists = get_keylists()
    sheets = wbk.read_sheets(data)
    if list_id == "plant-areas":
        old = lists.plant_areas()
        return wbk.import_plant_areas(sheets, old), [n.tag for n in old.nodes]
    if list_id == "equipment-packages":
        old = lists.equipment_packages()
        return wbk.import_equipment_packages(sheets, old, lists.master_columns().all()), [p.number for p in old.items]
    if list_id == "load-types":
        old = lists.load_types()
        return wbk.import_load_types(sheets, old, lists.master_columns().all()), [t.name for t in old.items]
    if list_id in wbk.CODE_HEADS:
        old = lists.code_list(list_id).items
        return wbk.import_code_list(sheets, list_id, old, lists.disciplines()), [c.code for c in old]
    if list_id == "cable-types":
        old = lists.cable_types().items
        return wbk.import_cable_types(sheets, old), [c.code for c in old]
    if list_id == "motors":
        old = lists.motors().items
        return wbk.import_motors(sheets, old), [m.part_no for m in old]
    if list_id == "drives":
        old = lists.drives().items
        return wbk.import_drives(sheets, old), [f"{d.cat_no} {d.voltage}V" for d in old]
    if list_id == "instrument-types":
        old = lists.instrument_types().items
        return wbk.import_instrument_types(sheets, old), [t.name for t in old]
    if list_id == "load-factors":
        old = lists.load_factors().items
        return wbk.import_load_factors(sheets, old), [r.equipment_type for r in old]
    if list_id == "starters":
        cur = lists.starters()
        return wbk.import_starters(sheets, cur), [f"{s.chart} {s.kw:g} kW" for s in cur.items]
    if list_id == "eel":
        old = lists.eel()
        return wbk.import_eel(sheets, old, _eel_names()), [i.tag for i in old.items]
    if list_id in REGISTERS:
        old = (lists.drawing_list() if list_id == "drawing-list" else lists.document_list()).items
        return wbk.import_register(sheets, REGISTERS[list_id], old), [d.number for d in old]
    if list_id == "instrument-runsheet":
        return wbk.import_instrument_runsheet(sheets), []
    rows = loadlist_api.current_rows()[0]
    if list_id == "load-list":
        return wbk.import_load_list(sheets, rows, [(n.id, n.tag) for n in lists.plant_areas().nodes],
                                    load_type_names(lists.load_types().items)), []
    old = lists.distribution_panels()
    return wbk.import_distribution_panels(sheets, old, {r.ref(): r for r in rows}), [p.tag for p in old.panels]


def _problems(fields: dict[str, str], labels: dict[str, str], detail: str) -> str:
    """One message for a refused file: each problem with the name of the row it is on."""
    lines = []
    for field, message in fields.items():
        item = labels.get(field.split(".")[0], "")
        lines.append(f"{item}: {message}" if item else message)
    lines = list(dict.fromkeys(lines))
    if not lines:
        return detail
    return f"{detail} " + "; ".join(lines[:8]) + (f"; and {len(lines) - 8} more" if len(lines) > 8 else "") + "."


def _check(list_id: str, parsed: wbk.Parsed) -> None:
    """The list's own checks on what the file says (raises RefValidationError). The lists whose
    checks need the rest of the project (Electrical Equipment List, Load List) are checked when applied."""
    p = parsed.payload
    if list_id == "plant-areas":
        check_plant_areas(PlantAreaList.model_validate(p))
    elif list_id == "equipment-packages":
        check_equipment_packages(EquipmentPackageList.model_validate(p), get_keylists().master_columns().all())
    elif list_id == "load-types":
        check_load_types(p["items"], get_keylists().master_columns().all())  # type: ignore[index]
    elif list_id in wbk.CODE_HEADS:
        check_code_list(p["items"], EquipmentCode if list_id == "equipment-codes" else InstrumentCode, LISTS[list_id][0],  # type: ignore[index]
                        get_keylists().disciplines())
    elif list_id == "cable-types":
        check_cable_types(p["items"])  # type: ignore[index]
    elif list_id == "motors":
        from workbench_core.keylists.motors import check_motors
        check_motors(p["items"])  # type: ignore[index]
    elif list_id == "drives":
        from workbench_core.keylists.drives import check_drives
        check_drives(p["items"])  # type: ignore[index]
    elif list_id == "starters":
        from workbench_core.keylists.starters import check_starters
        check_starters(p["items"], p["default_chart"])  # type: ignore[index]
    elif list_id == "load-factors":
        from workbench_core.keylists.load_factors import check_load_factors
        check_load_factors(p["items"])  # type: ignore[index]
    elif list_id == "instrument-types":
        from workbench_core.keylists.instrument_types import check_instrument_types
        check_instrument_types(p["items"])  # type: ignore[index]
    elif list_id in REGISTERS:
        drawing_list_api.checked(p["items"], REGISTERS[list_id])  # type: ignore[index]
    elif list_id == "instrument-runsheet":
        instrument_runsheet_api.checked(p)  # type: ignore[arg-type]
    elif list_id == "distribution-panels":
        _, errors = check_panels(p, {r.ref(): r for r in get_loadlist().rows()})  # type: ignore[arg-type]
        if errors:
            raise RefValidationError(f"{len(errors)} problem(s) in the panels.", errors)


def _save(list_id: str, parsed: wbk.Parsed):
    """Save through the list's own route, so the same rules apply. Returns its answer."""
    p = parsed.payload
    lists = get_keylists()
    if list_id == "plant-areas":
        return keylists_api.update_plant_areas(keylists_api.PlantAreasUpdate.model_validate(p))
    if list_id == "equipment-packages":
        return keylists_api.update_equipment_packages(keylists_api.EquipmentPackagesUpdate.model_validate(p))
    if list_id == "load-types":
        return keylists_api.update_load_types(keylists_api.LoadTypesUpdate.model_validate(p))
    if list_id in wbk.CODE_HEADS:
        items = check_code_list(p["items"], EquipmentCode if list_id == "equipment-codes" else InstrumentCode, LISTS[list_id][0],  # type: ignore[index]
                                lists.disciplines())
        if list_id == "equipment-codes":
            kept = {i.id for i in items}
            keylists_api._refuse_eel(("equipment_code_id",), {c.id: c.code for c in lists.code_list(list_id).items
                                                              if c.id not in kept}, "equipment codes")
        return lists.save_code_list(list_id, items)
    if list_id == "cable-types":
        return lists.save_cable_types(check_cable_types(p["items"]), note="Imported from a workbook")  # type: ignore[index]
    if list_id == "motors":
        from workbench_core.keylists.motors import check_motors
        return lists.save_motors(check_motors(p["items"]), note="Imported from a workbook")  # type: ignore[index]
    if list_id == "drives":
        from workbench_core.keylists.drives import check_drives
        return lists.save_drives(check_drives(p["items"]), note="Imported from a workbook")  # type: ignore[index]
    if list_id == "instrument-types":
        from workbench_core.keylists.instrument_types import check_instrument_types
        return lists.save_instrument_types(check_instrument_types(p["items"]), note="Imported from a workbook")  # type: ignore[index]
    if list_id == "load-factors":
        from workbench_core.keylists.load_factors import check_load_factors
        return lists.save_load_factors(check_load_factors(p["items"]), note="Imported from a workbook")  # type: ignore[index]
    if list_id == "starters":
        from workbench_core.keylists.starters import check_starters
        return lists.save_starters(check_starters(p["items"], p["default_chart"]), note="Imported from a workbook")  # type: ignore[index]
    if list_id == "eel":
        return eel_api.save_eel(eel_api.EelUpdate.model_validate(p))
    if list_id in REGISTERS:
        return drawing_list_api.save_register(REGISTERS[list_id], drawing_list_api.RegisterBody(items=p["items"]))  # type: ignore[index]
    if list_id == "instrument-runsheet":
        return instrument_runsheet_api.save_runsheet(instrument_runsheet_api.RunsheetBody(rows=p))  # type: ignore[arg-type]
    return distribution_panels_api.save_panels(p)  # type: ignore[arg-type]


def _apply_load_list(parsed: wbk.Parsed) -> list[str]:
    """Make the file's changes to the Load List's rows, one row at a time (each is in the change
    log). Panels are made first and unmade last, so rows can be supplied from them. Returns
    notes: how many rows changed and which were refused."""
    areas, types = loadlist_api._choices()
    labels = {c.id: c.label for c in areas + types}
    store = get_loadlist()
    done: set[str] = set()
    refused: list[str] = []
    steps = (lambda c: {k: v for k, v in c.items() if k == "is_panel" and v is True},
             lambda c: {k: v for k, v in c.items() if k != "is_panel"},
             lambda c: {k: v for k, v in c.items() if k == "is_panel" and v is False})
    for step in steps:
        for row, change in parsed.payload:  # type: ignore[union-attr]
            part = step(change)
            if not part:
                continue
            try:
                loadlist_api._check_cable(part)
                store.allocate([(row.recipe_id, row.key)], part, labels)
                done.add(row.ref())
            except RefValidationError as exc:
                refused.append(f"{row.tag()}: {exc.message}")
            except NotFound:
                refused.append(f"{row.tag()}: no longer in the Load List")
    notes = [f"{len(done)} row(s) changed."]
    if refused:
        notes.append(f"{len(refused)} change(s) were refused: " + " ".join(list(dict.fromkeys(refused))[:8]))
    return notes


@router.post("/{list_id}/import", response_model=ImportPreview)
async def import_list(list_id: str, request: Request, filename: str = Query(...), apply: bool = Query(False)):
    """Read a workbook for a list. Without `apply` nothing is saved (a preview); with it the
    file replaces the list (for the Load List: changes the rows it names)."""
    name, item = _known(list_id), LISTS[list_id][1]
    if list_id in READ_ONLY:
        raise HTTPException(400, f"The {name} list is read-only here: it changes in List import.")
    data = await read_upload(request, MAX_UPLOAD)
    try:
        parsed, old = await run_in_threadpool(_parse, list_id, data)
    except ValueError as exc:
        raise HTTPException(400, f"Could not read {Path(filename).name}: {exc}") from exc
    try:
        _check(list_id, parsed)
    except RefValidationError as exc:
        return JSONResponse(status_code=422, content={
            "detail": _problems(exc.fields, parsed.labels, "The file has problems:" if exc.fields else exc.message), "fields": {}})
    if list_id == "instrument-runsheet":
        summary = (f"{len(parsed.payload)} row(s) in the file. "  # type: ignore[arg-type]
                   f"They replace the {len(get_keylists().instrument_runsheet().rows)} row(s) of the list.")
    elif list_id == "load-list":
        summary = f"{len(parsed.keys)} row(s) of the Load List would change."
    else:
        have = {name_key(k) for k in old}
        new = sum(1 for k in parsed.keys if name_key(k) not in have)
        gone = len(have - {name_key(k) for k in parsed.keys})
        summary = (f"{len(parsed.keys)} {item}(s) in the file: {new} new, {len(parsed.keys) - new} already in the list. "
                   + (f"{gone} {item}(s) of the list are not in the file and would be removed." if gone else
                      "Nothing would be removed."))
    preview = ImportPreview(summary=summary, notes=parsed.notes)
    if not apply:
        return preview
    if list_id == "load-list":
        return preview.model_copy(update={"applied": True, "notes": parsed.notes + _apply_load_list(parsed)})
    try:
        result = _save(list_id, parsed)
    except RefValidationError as exc:
        return JSONResponse(status_code=422, content={"detail": _problems(exc.fields, parsed.labels, exc.message), "fields": {}})
    if isinstance(result, JSONResponse):  # the list's save refused it
        body = json.loads(bytes(result.body))
        return JSONResponse(status_code=result.status_code, content={
            "detail": _problems(body.get("fields") or {}, parsed.labels, f"{name} was not changed: {body.get('detail', '')}"),
            "fields": {}})
    return preview.model_copy(update={"applied": True})


# -- reset -----------------------------------------------------------------------------------------

class ResetResult(BaseModel):
    message: str


@router.post("/{list_id}/reset", response_model=ResetResult)
def reset_list(list_id: str):
    """Empty a project list (Cable Types: back to the default set). It goes through the list's
    own save, so a list whose rows are in use elsewhere is refused, with the reason.

    The Load List is different: its rows come from the imports. Resetting it forgets every
    remembered row (allocations a person chose, cable details, rows kept as deleted) and reads
    the imports again, so what is left is exactly what the latest files give, filled in
    automatically where it can be."""
    lists = get_keylists()
    if list_id == "plc":
        from workbench_core.keylists.plc import PlcList
        lists.save_plc(PlcList(), note="Reset to empty")
        return ResetResult(message="The PLC List is empty. The card and rack types are kept.")
    name = _known(list_id)
    if list_id in READ_ONLY:
        raise HTTPException(400, f"The {name} list is read-only here: it changes in List import.")
    if list_id == "load-list":
        gone = get_loadlist().reset().get("all", 0)
        rows = [r for r in loadlist_api.current_rows()[0] if r.status == "active"]
        return ResetResult(message=f"{gone} remembered row(s) forgotten. The imports were read again: {len(rows)} row(s).")
    if list_id == "drives":
        from workbench_core.keylists.drives import default_drives
        items = lists.save_drives(default_drives(), note="Reset to the PowerFlex 755TS drives").items
        return ResetResult(message=f"Drive Data is back to the {len(items)} PowerFlex 755TS drives.")
    if list_id == "instrument-types":
        from workbench_core.keylists.instrument_types import default_instrument_types
        items = lists.save_instrument_types(default_instrument_types(), note="Reset to the common instrument types").items
        return ResetResult(message=f"Instrument Types is back to the {len(items)} common types.")
    if list_id == "load-factors":
        from workbench_core.keylists.load_factors import default_load_factors
        items = lists.save_load_factors(default_load_factors(), note="Reset to the typical load factors").items
        return ResetResult(message=f"Load Factors is back to the {len(items)} typical rows (with Default).")
    if list_id == "starters":
        from workbench_core.keylists.starters import StarterList, default_starters
        items = lists.save_starters(StarterList(items=default_starters()), note="Reset to the NHP Type 2 charts").items
        return ResetResult(message=f"Starter Coordination is back to the {len(items)} rows of NHP's six Type 2 charts (default chart ECH64.2).")
    if list_id == "motors":
        from workbench_core.keylists.motors import default_motors
        items = lists.save_motors(default_motors(), note="Reset to the WEG W22 motors").items
        return ResetResult(message=f"Motor Data is back to the {len(items)} WEG W22 motors.")
    if list_id == "cable-types":
        from workbench_core.keylists.cable_types import default_cable_types
        items = lists.save_cable_types(default_cable_types(), note="Reset to the default cable types").items
        return ResetResult(message=f"Cable Types is back to the {len(items)} default cable types.")
    empty = {"plant-areas": {"nodes": []}, "equipment-packages": {"items": [], "types": []},
             "distribution-panels": wbk.DistributionPanelList(), "instrument-runsheet": []}.get(list_id, {"items": []})
    try:
        result = _save(list_id, wbk.Parsed(empty, []))
    except RefValidationError as exc:
        return JSONResponse(status_code=422, content={"detail": f"{name} was not reset: {exc.message}", "fields": {}})
    if isinstance(result, JSONResponse):
        body = json.loads(bytes(result.body))
        return JSONResponse(status_code=result.status_code, content={
            "detail": _problems(body.get("fields") or {}, {}, f"{name} was not reset: {body.get('detail', '')}"), "fields": {}})
    return ResetResult(message=f"{name} is empty.")
