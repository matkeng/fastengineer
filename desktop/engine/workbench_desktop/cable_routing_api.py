# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Cable Routing: the node map of the cable ladder routes, the cables' routes over it and the
ladders' loading (see workbench_core.keylists.cable_routing)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from workbench_core.generators.models import BuildResult, BuildStats, GeneratorConfig, OutputRow
from workbench_core.generators.xlsx_export import csv_bytes, xlsx_bytes
from workbench_core.keylists.cable_routing import (CableRoute, CableRouting, EquipmentChoice, SegmentLoad, check_routing, compute,
                                                   equipment_of, follow_equipment, renumber)
from workbench_core.refdata import RefValidationError
from workbench_core.refdata.validate import name_key

from .exporting import save_to
from .master_api import MEDIA, Inputs, inputs, master_of
from .refdata_api import invalid
from .storage import get_keylists

router = APIRouter(prefix="/api/cable-routing", tags=["cable routing"])


class Endpoint(BaseModel):
    """A From or To of the cable schedule that is not on the map yet."""
    tag: str
    cables: int
    in_equipment_list: bool


class RoutingView(BaseModel):
    doc: CableRouting
    errors: dict[str, str]  # field -> message (they block a save)
    warnings: list[str]
    equipment: list[EquipmentChoice]  # the Project Master Equipment List, to place
    unplaced: list[Endpoint]
    cables: list[CableRoute]
    segments: list[SegmentLoad]


def _view(doc: CableRouting, src: Inputs | None = None) -> RoutingView:
    src = src or inputs()
    equipment = equipment_of(master_of("equipment_list", src)[0])
    doc, errors, warnings = check_routing(follow_equipment(doc, equipment))
    done = compute(doc, master_of("cable_schedule", src, routed=False)[0], src.cables)
    placed = {name_key(p.tag) for p in doc.placements}
    for e in equipment:
        e.placed = name_key(e.tag) in placed
    listed = {name_key(e.tag) for e in equipment}
    ends: dict[str, Endpoint] = {}
    for c in done.cables:
        for tag in (c.from_tag, c.to_tag):
            if tag and name_key(tag) not in placed:
                e = ends.setdefault(name_key(tag), Endpoint(tag=tag, cables=0, in_equipment_list=name_key(tag) in listed))
                e.cables += 1
    return RoutingView(doc=doc, errors=errors, warnings=warnings + done.warnings, equipment=equipment,
                       unplaced=sorted(ends.values(), key=lambda e: (-e.cables, e.tag)), cables=done.cables, segments=done.segments)


@router.get("", response_model=RoutingView)
def get_routing() -> RoutingView:
    """The map, with the cable schedule's cables routed over it."""
    return _view(get_keylists().cable_routing())


@router.put("", response_model=RoutingView)
def save_routing(body: CableRouting):
    src = inputs()
    doc, errors, _ = check_routing(follow_equipment(body, equipment_of(master_of("equipment_list", src)[0])))
    if errors:
        return invalid(RefValidationError(f"{len(errors)} problem(s) in the cable routing map: "
                                          + "; ".join(sorted(set(errors.values()))[:3]) + ".", errors))
    return _view(get_keylists().save_cable_routing(doc), src)


@router.post("/check", response_model=RoutingView)
def check_draft(body: CableRouting) -> RoutingView:
    """The routes, ladders and errors of unsaved edits (nothing is saved)."""
    return _view(body)


@router.post("/renumber", response_model=RoutingView)
def renumber_draft(body: CableRouting) -> RoutingView:
    """The nodes and segments numbered again from 1 (nothing is saved)."""
    return _view(renumber(body))


class ExportBody(BaseModel):
    table: Literal["cables", "segments"] = "cables"
    format: Literal["xlsx", "csv"] = "xlsx"
    path: str | None = None  # desktop: chosen in a Save As dialog


def _table(view: RoutingView, table: str) -> BuildResult:
    services = {s.id: s.name for s in view.doc.services}
    if table == "cables":
        header = ["Cable Number", "From", "To", "Cable Code", "Service", "Overall Diameter (mm)", "Mass (kg/m)", "Route",
                  "Route Length (m)", "Length (m)", "Status"]
        rows = [[c.number, c.from_tag, c.to_tag, c.cable_code, services.get(c.service_id, ""), c.od_mm, c.mass_kg_per_m, c.route,
                 c.route_m, c.length_m, c.status + (" (route given)" if c.overridden else "")] for c in view.cables]
    else:
        header = ["Segment", "Length (m)", "Service", "Cables", "Trefoils", "Cables' Width (mm)", "Required Width (mm)",
                  "Ladder Width (mm)", "Ladders", "Fill (%)", "Mass (kg/m)", "Limit (kg/m)", "Notes"]
        rows = []
        for s in view.segments:
            rows += [[s.tag, s.length_m, services.get(x.service_id, ""), x.cables, x.trefoils, x.sum_od_mm, x.required_mm, x.width_mm,
                      x.ladders, x.fill_pct, x.kg_per_m, x.max_kg_per_m, "; ".join(x.flags)] for x in s.services]
            if not s.services:
                rows.append([s.tag, s.length_m, "", 0, 0, None, None, None, None, None, None, None, "no cables"])
    return BuildResult(header=header, rows=[OutputRow(cells=r) for r in rows],
                       stats=BuildStats(rows_written=len(rows), output_rows=len(rows)), engine_version="cable routing")


@router.post("/export")
def export_routing(body: ExportBody, request: Request):
    """The cables' routes or the segments' ladders, as saved, as a file."""
    if not request.headers.get("content-type", "").startswith("application/json"):
        raise HTTPException(415, "Expected application/json")
    name = "Cable Routes" if body.table == "cables" else "Cable Ladder Segments"
    result = _table(_view(get_keylists().cable_routing()), body.table)
    cfg = GeneratorConfig(doc_title=name)
    data = xlsx_bytes(result, cfg) if body.format == "xlsx" else csv_bytes(result, cfg.date_format)
    if body.path is None:
        return Response(data, media_type=MEDIA[body.format], headers={"Content-Disposition": f'attachment; filename="{name}.{body.format}"'})
    return save_to(body.path, data, f".{body.format}")
