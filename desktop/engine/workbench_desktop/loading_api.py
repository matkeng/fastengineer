# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Board Loading: the demand below every board of the Load List, against its rating (keylists.loading)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel

from workbench_core.keylists.loading import WARN_AT, LoadingReport, board_loading

from .exporting import save_to
from .storage import get_keylists

router = APIRouter(prefix="/api/loading", tags=["project master lists"])
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _report(warn_at: float) -> LoadingReport:
    from .loadlist_api import current_rows

    lists = get_keylists()
    return board_loading(current_rows()[0], {t.id: t for t in lists.load_types().items},
                         {n.id: (n.tag, n.description) for n in lists.plant_areas().nodes}, lists.motors().items,
                         lists.drives().items, lists.starters(), lists.load_factors().items, warn_at=warn_at)


@router.get("", response_model=LoadingReport)
def get_loading(warn_at: float = Query(WARN_AT, gt=0, le=1000)) -> LoadingReport:
    """Every board with what is below it, worked out on the Load List as it is. Nothing is stored."""
    return _report(warn_at)


class ExportBody(BaseModel):
    path: str | None = None  # desktop: chosen in a Save As dialog
    warn_at: float = WARN_AT


@router.post("/export")
def export_loading(body: ExportBody, request: Request):
    """The report as a workbook: the boards, then the loads that could not be counted."""
    from workbench_core.keylists.workbooks import write_sheets

    if not request.headers.get("content-type", "").startswith("application/json"):
        raise HTTPException(415, "Expected application/json")
    rep = _report(body.warn_at)
    boards = [["Board", "Description", "Level", "Supplied from", "Loads", "Connected kW", "Max demand kW", "Average kW",
               "Max demand kVA", "Max demand A", "Rating", "Rating unit", "Loading %", "Spare", "Loads not counted", "Problems"]]
    for b in rep.boards:
        problems = "; ".join(p for p in (b.problem, f"At or above {rep.warn_at:g} %" if b.over else "") if p)
        boards.append([b.tag, b.description or None, b.depth, b.supplied_from or None, b.loads, b.connected_kw, b.max_kw, b.avg_kw,
                       b.max_kva, b.max_amps, b.rating, b.rating_unit or None, b.loading_pct, b.spare, b.left_out or None,
                       problems or None])
    left = [["Load", "Supplied from", "Why it is not counted"], *[[x.tag, x.supplied_from or None, x.reason] for x in rep.left_out]]
    notes = [["Board Loading"], ["Max demand kW = rating x nameplate load factor x maximum demand factor, summed for every load below the board."],
             ["There is no diversity between boards."],
             [f"kVA = kW / power factor: the load's motor's at full load, {rep.default_pf:g} when it has no motor."],
             ["A board's loading is its maximum demand over its own rating, in the rating's unit."]]
    data = write_sheets([("Boards", boards), ("Not counted", left), ("Notes", notes)])
    if body.path is None:
        return Response(data, media_type=XLSX, headers={"Content-Disposition": 'attachment; filename="Board Loading.xlsx"'})
    return save_to(body.path, data, ".xlsx")
