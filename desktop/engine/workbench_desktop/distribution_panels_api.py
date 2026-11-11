# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Distribution Panels: each panel's schedule, its circuits taken from the Project Load List
(see workbench_core.keylists.distribution_panels)."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from workbench_core.keylists import LoadListRow, LoadType
from workbench_core.keylists.distribution_panels import (CB_RATINGS, KIND_LABELS, SPARE_SPACE, DistributionPanel,
                                                         DistributionPanelList, PanelSchedule, auto_place, check_panels,
                                                         resolve)
from workbench_core.keylists.loadgen import ordered
from workbench_core.refdata import RefValidationError

from .loadlist_api import Choice, current_rows
from .refdata_api import invalid
from .storage import get_deliverables, get_keylists, get_loadlist

router = APIRouter(prefix="/api/distribution-panels", tags=["distribution panels"])


class PanelsView(BaseModel):
    doc: DistributionPanelList
    schedules: dict[str, PanelSchedule]  # panel id -> its schedule, worked out
    errors: dict[str, str]  # field -> message (they block a save)
    load_panels: list[Choice]  # the Load List's distribution panels (id: the row's ref)
    cb_ratings: list[int]
    kinds: dict[str, str]  # entry kind -> what its Load Type column shows
    spare_space: str


def _context(rows: list[LoadListRow] | None = None) -> tuple[dict[str, LoadListRow], dict[str, LoadType]]:
    """(Load List rows by ref, load types by id). Without `rows`, the rows as last remembered."""
    rows = get_loadlist().rows() if rows is None else rows
    return {r.ref(): r for r in rows}, {t.id: t for t in get_keylists().load_types().items}


def _view(doc: DistributionPanelList, loads: dict[str, LoadListRow], load_types: dict[str, LoadType]) -> PanelsView:
    doc, errors = check_panels(doc, loads)
    panels = [Choice(id=r.ref(), label=" – ".join(x for x in (r.tag(), str(r.values.get("desc") or "").strip()) if x))
              for r in ordered(list(loads.values())) if r.is_panel]
    return PanelsView(doc=doc, schedules={p.id: resolve(p, loads, load_types) for p in doc.panels}, errors=errors,
                      load_panels=panels, cb_ratings=list(CB_RATINGS), kinds=KIND_LABELS, spare_space=SPARE_SPACE)


def schedule_of(panel_id: str) -> tuple[DistributionPanel | None, PanelSchedule | None]:
    """A panel and its schedule as they are now (for a deliverable); (None, None) if it is gone."""
    loads, load_types = _context(current_rows()[0])
    panel = next((p for p in get_keylists().distribution_panels().panels if p.id == panel_id), None)
    return (panel, resolve(panel, loads, load_types)) if panel else (None, None)


@router.get("", response_model=PanelsView)
def get_panels() -> PanelsView:
    """The panels, with the Load List brought up to date first."""
    return _view(get_keylists().distribution_panels(), *_context(current_rows()[0]))


@router.put("", response_model=PanelsView)
def save_panels(body: DistributionPanelList):
    lists = get_keylists()
    loads, load_types = _context()
    doc, errors = check_panels(body, loads)
    kept = {p.id for p in doc.panels}
    for old in lists.distribution_panels().panels:
        used = get_deliverables().using_panel(old.id) if old.id not in kept else []
        if used:
            errors[f"{old.id}.delete"] = f"{old.tag} is issued by the deliverable(s) {', '.join(used)}. Delete those first."
    if errors:
        return invalid(RefValidationError(f"{len(errors)} problem(s) in the Distribution Panels: "
                                          + "; ".join(sorted(set(errors.values()))[:3]) + ".", errors))
    return _view(lists.save_distribution_panels(doc), loads, load_types)


@router.post("/check", response_model=PanelsView)
def check_draft(body: DistributionPanelList) -> PanelsView:
    """The schedules, totals and errors of unsaved edits (nothing is saved)."""
    return _view(body, *_context())


class PlaceBody(BaseModel):
    doc: DistributionPanelList
    panel_id: str


@router.post("/place", response_model=PanelsView)
def place(body: PlaceBody) -> PanelsView:
    """Put the loads of one panel that are on no way yet on its free ways (nothing is saved)."""
    loads, load_types = _context()
    doc = body.doc.model_copy(update={"panels": [auto_place(p, loads, load_types) if p.id == body.panel_id else p
                                                  for p in body.doc.panels]})
    return _view(doc, loads, load_types)
