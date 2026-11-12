# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""FastAPI adapter. Keep this thin: all real work belongs in workbench_core."""

from __future__ import annotations

import re

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import workbench_core
from workbench_core.hello import EngineInfo, Greeting
from workbench_core.model import Equipment

from . import identity, projects
from .audit import Conflict
from .audit_api import router as audit_router
from .dashboard_api import router as dashboard_router
from .excel_api import router as excel_router
from .mel_api import router as mel_router
from .symbols_api import router as symbols_router
from .refdata_api import router as refdata_router
from .generators_api import router as generators_router
from .keylists_api import router as keylists_router
from .loadlist_api import mel_router as mel_list_router
from .loadlist_api import router as loadlist_router
from .eel_api import router as eel_router
from .plc_api import router as plc_router
from .distribution_panels_api import router as distribution_panels_router
from .instrument_runsheet_api import router as instrument_runsheet_router
from .master_api import columns_router as master_columns_router, load_fields_router, router as master_router
from .load_summary_api import router as load_summary_router
from .drawing_list_api import document_router, enums_router, router as drawing_list_router
from .keylist_workbooks_api import router as keylist_workbooks_router
from .deliverables_api import router as deliverables_router
from .projects_api import router as projects_router
from .sample_api import router as sample_router
from .storage import get_store

app = FastAPI(title="Drawing Workbench engine", version=workbench_core.__version__)

# URLs that address one editable record. A GET or PUT of one returns the record's
# version as an ETag; the client sends it back as If-Match, and a save made against an
# older version is refused (see audit.check) instead of overwriting a colleague's work.
_RECORD_URLS = [(re.compile(p), entity) for p, entity in (
    (r"^/api/ref/enums/([^/]+)$", "ref_enum"),
    (r"^/api/ref/trees/([^/]+)$", "ref_tree"),
    (r"^/api/ref/tables/([^/]+)$", "ref_table"),
    (r"^/api/keylists/(plant-areas)$", "plant_areas"),
    (r"^/api/keylists/(equipment-packages)$", "equipment_packages"),
    (r"^/api/keylists/(load-types)$", "load_types"),
    (r"^/api/keylists/(equipment-codes)$", "equipment_codes"),
    (r"^/api/keylists/(instrument-codes)$", "instrument_codes"),
    (r"^/api/keylists/(cable-types)$", "cable_types"),
    (r"^/api/keylists/(motors)$", "motors"),
    (r"^/api/keylists/(drives)$", "drives"),
    (r"^/api/(eel)$", "eel"),
    (r"^/api/mel/recipes/([^/]+)$", "mel_recipe"),
    (r"^/api/symbols/libraries/([^/]+)$", "sym_library"),
    (r"^/api/symbols/templates/([^/]+)$", "sym_template"),
    (r"^/api/symbols/drawings/([^/]+)$", "sym_drawing"),
    (r"^/api/plc/(catalogue)$", "gen_catalogue"),
    (r"^/api/(plc)$", "plc"),
    (r"^/api/(distribution-panels)$", "distribution_panels"),
    (r"^/api/(instrument-runsheet)$", "instrument_runsheet"),
    (r"^/api/(enums)$", "enums"),
    (r"^/api/(master-columns)$", "master_columns"),
    (r"^/api/(load-fields)$", "load_fields"),
    (r"^/api/(load-summary)$", "load_summary"),
    (r"^/api/(drawing-list)$", "drawing_list"),
    (r"^/api/(document-list)$", "document_list"),
    (r"^/api/deliverables/([^/]+)$", "deliverable"),
    (r"^/api/generators/([^/]+)$", "generator"),
)]


def record_of(path: str) -> tuple[str, str] | None:
    for pattern, entity in _RECORD_URLS:
        m = pattern.match(path)
        if m:
            return entity, m.group(1)
    return None


# Added first so it sits inside CORS: its 401 then still carries the CORS headers.
app.add_middleware(identity.IdentityMiddleware, record_of=record_of, resolve_project=projects.resolve,
                   version_of=lambda entity, record_id: get_store().version_of(entity, record_id))

# The Tauri WebView origin differs by OS (http://tauri.localhost on Windows,
# tauri://localhost on macOS/Linux); Vite dev server runs on localhost:5173.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^(https?://tauri\.localhost|tauri://localhost|http://localhost:\d+|http://127\.0\.0\.1:\d+)$",
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
    expose_headers=["ETag"],
)


@app.exception_handler(projects.ProjectError)
def project_error(_: Request, exc: projects.ProjectError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content={
        "detail": exc.message, "fields": {exc.field: exc.message} if exc.field else {}})


@app.exception_handler(Conflict)
def conflict(_: Request, exc: Conflict) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc), "conflict": True,
                                                  "changed_by": exc.changed_by, "changed_at": exc.changed_at})



app.include_router(excel_router)
app.include_router(mel_router)
app.include_router(refdata_router)
app.include_router(keylists_router)
app.include_router(loadlist_router)
app.include_router(mel_list_router)
app.include_router(eel_router)
app.include_router(plc_router)
app.include_router(distribution_panels_router)
app.include_router(instrument_runsheet_router)
app.include_router(master_router)
app.include_router(master_columns_router)
app.include_router(load_fields_router)
app.include_router(load_summary_router)
app.include_router(enums_router)
app.include_router(drawing_list_router)
app.include_router(document_router)
app.include_router(keylist_workbooks_router)
app.include_router(deliverables_router)
app.include_router(symbols_router)
app.include_router(generators_router)
app.include_router(dashboard_router)
app.include_router(audit_router)
app.include_router(projects_router)
app.include_router(sample_router)


@app.get("/api/whoami")
def whoami() -> dict[str, object]:
    """Who the engine thinks is calling, and whether it is a shared server."""
    ctx = identity.current()
    name = projects.registry().get(ctx.project)["name"] if ctx.project else None
    return {"user": ctx.user, "machine": ctx.machine, "server": identity.server_mode,
            "host": identity.local_machine(), "is_admin": projects.is_admin(ctx.user),
            "project": {"id": ctx.project, "name": name} if ctx.project else None}


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/info", response_model=EngineInfo)
def info() -> EngineInfo:
    return workbench_core.engine_info()


@app.get("/api/hello", response_model=Greeting)
def hello(name: str = "world") -> Greeting:
    return workbench_core.greet(name)


@app.get("/api/model/demo", response_model=list[Equipment])
def model_demo() -> list[Equipment]:
    return workbench_core.demo_equipment()
