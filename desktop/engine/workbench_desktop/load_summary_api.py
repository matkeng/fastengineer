# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""The Load List Summary Page: tables totalling up the Load List (keylists.load_summary)."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from workbench_core.keylists.load_summary import FUNCS, SummaryOutTable, SummaryPage, check_page, work_out
from workbench_core.refdata import RefValidationError

from .refdata_api import invalid
from .storage import get_keylists

router = APIRouter(prefix="/api/load-summary", tags=["project master lists"])
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class Choice(BaseModel):
    key: str
    label: str


class SummaryView(BaseModel):
    page: SummaryPage
    tables: list[SummaryOutTable]  # the page worked out on the Load List as it is
    fields: list[Choice]  # what an aggregate can total: the Load List's fields, then what the app works out
    refs: list[Choice]  # what a filter or condition can use about a load
    funcs: dict[str, str]


def _names() -> tuple[list[Choice], list[Choice]]:
    from workbench_core.keylists.load_calcs import APP_REFS, MOTOR_REFS
    from workbench_core.keylists.loadgen import TAGS

    lf = get_keylists().load_fields()
    fields = [Choice(key=f.key, label=f.label + (" (calculated)" if f.kind == "calc" else "")) for f in lf.fields]
    app = [Choice(key=r, label=m) for r, m in APP_REFS + MOTOR_REFS] + [Choice(key=t.casefold(), label=m) for t, m in TAGS]
    seen: set[str] = set()
    refs = []
    for c in [Choice(key=f.key, label=f.label) for f in lf.fields] + app:
        if c.key not in seen:
            seen.add(c.key)
            refs.append(c)
    numeric_app = [c for c in app if c.key in ("rating", "voltage", "qty", "cable_length", "cable_size", "earth_size", "cable_parallel")
                   or c.key in ("motor.kw", "motor.flc", "motor.eff100", "motor.pf100", "motor.weight", "motor.torque",
                                "drive.amps", "drive.kw", "drive.hp")]
    return fields + numeric_app, refs


def _work_out(page: SummaryPage) -> list[SummaryOutTable]:
    from .loadlist_api import current_rows

    lists = get_keylists()
    return work_out(page, current_rows()[0], {t.id: t for t in lists.load_types().items},
                    {n.id: (n.tag, n.description) for n in lists.plant_areas().nodes}, lists.motors().items, lists.drives().items, lists.starters(), lists.load_factors().items)


def _view(page: SummaryPage) -> SummaryView:
    fields, refs = _names()
    return SummaryView(page=page, tables=_work_out(page), fields=fields, refs=refs, funcs=FUNCS)


@router.get("", response_model=SummaryView)
def get_summary() -> SummaryView:
    return _view(get_keylists().load_summary())


def _checked(body: SummaryPage) -> SummaryPage:
    _, refs = _names()
    return check_page(body, {c.key for c in refs})


@router.put("", response_model=SummaryView)
def save_summary(body: SummaryPage):
    try:
        page = _checked(body)
    except RefValidationError as exc:
        return invalid(exc)
    return _view(get_keylists().save_load_summary(page))


@router.post("/preview", response_model=SummaryView)
def preview_summary(body: SummaryPage):
    """The edited (unsaved) page worked out on the Load List as it is."""
    try:
        page = _checked(body)
    except RefValidationError as exc:
        return invalid(exc)
    return _view(page)


class ExportBody(BaseModel):
    path: str | None = None  # desktop: chosen in a Save As dialog


@router.post("/export")
def export_summary(body: ExportBody, request: Request):
    """The saved page, worked out now, as a workbook: a sheet per table."""
    from workbench_core.keylists.workbooks import write_sheets

    if not request.headers.get("content-type", "").startswith("application/json"):
        raise HTTPException(415, "Expected application/json")
    tables = _work_out(get_keylists().load_summary())
    sheets, used = [], set()
    for t in tables:
        title = re.sub(r"[\[\]:*?/\\]+", "-", t.name)[:31] or "Summary"
        n = 2
        while title.casefold() in used:
            title, n = f"{title[:28]} {n}", n + 1
        used.add(title.casefold())
        grid = [["Row", *t.columns, "Loads", "Problems"]]
        for r in t.rows:
            grid.append([r.name, *[None if v == "" else v for v in r.cells], r.loads,
                         "; ".join(f"{i.severity}: {i.message}" for i in r.issues) or None])
        sheets.append((title, grid))
    data = write_sheets(sheets or [("Summary", [["No tables yet"]])])
    if body.path is None:
        return Response(data, media_type=XLSX, headers={"Content-Disposition": 'attachment; filename="Load List Summary.xlsx"'})
    target = Path(body.path)
    if target.suffix.lower() != ".xlsx":
        target = target.with_suffix(".xlsx")
    try:
        target.write_bytes(data)
    except OSError as exc:
        raise HTTPException(409, f"Could not write {target}: {exc.strerror or exc}. Is it open in another program?") from exc
    return {"path": str(target)}
