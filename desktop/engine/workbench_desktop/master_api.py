# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""The Project Master lists: one Cable Schedule, Equipment List, Instrument List and IO List
for the project, filled by the Power and the Instrument generator together (see
workbench_core.keylists.master). They are worked out when asked for, and read only."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from workbench_core.generators.models import BuildResult, GeneratorConfig
from workbench_core.generators.xlsx_export import csv_bytes, xlsx_bytes
from workbench_core.keylists.loadgen import LISTS, generate, missing_load_types
from workbench_core.keylists.master import INSTRUMENT, MASTER_LISTS, MASTER_NAMES, POWER, generator_counts, master_columns, master_list

from .storage import get_keylists

router = APIRouter(prefix="/api/master", tags=["project master lists"])
MEDIA = {"csv": "text/csv", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}


class Inputs(BaseModel, arbitrary_types_allowed=True):
    """What the generators run from, read once for however many lists are wanted."""
    loads: list
    load_types: dict
    areas: dict  # plant area id -> (tag, description)
    cables: list
    runsheet: object
    equipment_types: dict
    columns: dict  # list key -> the project's columns of the list


def inputs() -> Inputs:
    from .loadlist_api import current_rows  # imported late: it runs the imports

    lists = get_keylists()
    return Inputs(loads=current_rows()[0], load_types={t.id: t for t in lists.load_types().items},
                  areas={n.id: (n.tag, n.description) for n in lists.plant_areas().nodes}, cables=lists.cable_types().items,
                  runsheet=lists.instrument_runsheet(), equipment_types={t.id: t for t in lists.equipment_packages().types},
                  columns=lists.master_columns().all())


def master_of(list_key: str, src: Inputs | None = None) -> tuple[BuildResult, list[str], list[str]]:
    """A master list as it is now: (the list, warnings, tags of the loads with no load type).
    Those loads add nothing to any list until a load type is allocated to them."""
    src = src or inputs()
    warnings: list[str] = []
    cols = src.columns[list_key]
    power = generate(list_key, src.loads, src.load_types, src.areas, src.cables, warnings, cols)
    result = master_list(list_key, power, src.runsheet, src.equipment_types, {i: a[0] for i, a in src.areas.items()},  # type: ignore[arg-type]
                         cols)
    if result.unresolved_count:
        warnings.append(f"{result.unresolved_count} tag(s) in the load types' or equipment types' rows match nothing and were left "
                        "as they are: " + ", ".join(result.unresolved_tokens[:10]))
    gone = sum(1 for r in src.runsheet.rows if r.equipment_type_id not in src.equipment_types)  # type: ignore[attr-defined]
    if gone:
        warnings.append(f"{gone} row(s) of the Instrument Runsheet have an equipment type that no longer exists and add nothing.")
    return result, warnings, missing_load_types(src.loads, src.load_types)


class MasterSummary(BaseModel):
    key: str
    name: str  # "Project Master Cable Schedule"
    deliverable_type: str  # the type of deliverable made from it
    columns: list[str]
    rows: int
    power_rows: int
    instrument_rows: int


@router.get("", response_model=list[MasterSummary])
def list_masters() -> list[MasterSummary]:
    src = inputs()
    out = []
    for key in MASTER_LISTS:
        result, _, _ = master_of(key, src)
        counts = generator_counts(result)
        out.append(MasterSummary(key=key, name=MASTER_NAMES[key], deliverable_type=LISTS[key].deliverable_type,
                                 columns=master_columns(key, src.columns[key]), rows=len(result.rows), power_rows=counts[POWER],
                                 instrument_rows=counts[INSTRUMENT]))
    return out


class MasterView(BaseModel):
    key: str
    name: str
    deliverable_type: str
    result: BuildResult
    warnings: list[str]
    missing_load_types: list[str]


def _known(list_key: str) -> str:
    if list_key not in MASTER_LISTS:
        raise HTTPException(404, "There is no project master list with that name.")
    return MASTER_NAMES[list_key]


@router.get("/{list_key}", response_model=MasterView)
def get_master(list_key: str) -> MasterView:
    name = _known(list_key)
    result, warnings, missing = master_of(list_key)
    return MasterView(key=list_key, name=name, deliverable_type=LISTS[list_key].deliverable_type, result=result, warnings=warnings,
                      missing_load_types=missing)


class ExportBody(BaseModel):
    format: Literal["xlsx", "csv"] = "xlsx"
    path: str | None = None  # desktop: chosen in a Save As dialog


@router.post("/{list_key}/export")
def export_master(list_key: str, body: ExportBody, request: Request):
    """The master list as it is now, as a file (not a revision: deliverables are what is issued)."""
    if not request.headers.get("content-type", "").startswith("application/json"):
        raise HTTPException(415, "Expected application/json")
    name = _known(list_key)
    result, _, _ = master_of(list_key)
    cfg = GeneratorConfig(doc_title=name)
    data = xlsx_bytes(result, cfg) if body.format == "xlsx" else csv_bytes(result, cfg.date_format)
    if body.path is None:
        return Response(data, media_type=MEDIA[body.format], headers={"Content-Disposition": f'attachment; filename="{name}.{body.format}"'})
    target = Path(body.path)
    if target.suffix.lower() != f".{body.format}":
        target = target.with_suffix(f".{body.format}")
    try:
        target.write_bytes(data)
    except OSError as exc:
        raise HTTPException(409, f"Could not write {target}: {exc.strerror or exc}. Is it open in another program?") from exc
    return {"path": str(target)}


# -- the project's columns of the master lists -------------------------------------------------

columns_router = APIRouter(prefix="/api/master-columns", tags=["project master lists"])


class ListColumns(BaseModel):
    key: str
    name: str  # "Project Master Cable Schedule"
    columns: list[str]
    protected: list[str]  # can be moved, not renamed or deleted
    defaults: list[str]  # the built-in columns


class ColumnsView(BaseModel):
    lists: list[ListColumns]
    extra: list[str]  # Generator and Confirmed: after every list's own columns, not edited
    reserved: list[str]


def _columns_view() -> ColumnsView:
    from workbench_core.keylists.master import EXTRA_COLUMNS
    from workbench_core.keylists.master_columns import PROTECTED, RESERVED

    cols = get_keylists().master_columns()
    return ColumnsView(lists=[ListColumns(key=k, name=MASTER_NAMES[k], columns=cols.of(k), protected=list(PROTECTED[k]),
                                          defaults=list(LISTS[k].columns)) for k in MASTER_LISTS],
                       extra=list(EXTRA_COLUMNS), reserved=list(RESERVED))


@columns_router.get("", response_model=ColumnsView)
def get_columns() -> ColumnsView:
    return _columns_view()


class ColumnsBody(BaseModel):
    lists: dict[str, list[dict]]  # list key -> [{name, was}] in the new order; lists left out are unchanged


class ListImpact(BaseModel):
    key: str
    name: str
    renames: dict[str, str]
    deletes: list[str]
    added: list[str]
    cells_dropped: int  # non-blank cells of load type and equipment type rows in deleted columns
    deliverables: list[str]  # names of the deliverables whose columns or filter change


class ColumnsSaved(BaseModel):
    view: ColumnsView
    impact: list[ListImpact]
    saved: bool


@columns_router.put("", response_model=ColumnsSaved)
def save_columns(body: ColumnsBody, dry_run: bool = False):
    """Save the project's columns of the master lists. A rename follows in the load types' and
    equipment types' rows and in deliverables' column choices and filters; a delete drops
    those cells and takes the column out of those deliverables. Issued revisions keep the
    columns they were issued with. `dry_run`: only say what saving would do."""
    from workbench_core.keylists.master_columns import ColumnEdit, plan_change, rename_in, rewrite_rows
    from workbench_core.refdata import RefValidationError

    from .refdata_api import invalid
    from .storage import get_deliverables

    lists = get_keylists()
    try:
        edits = {k: [ColumnEdit.model_validate(c) for c in v] for k, v in body.lists.items()}
        changes = plan_change(lists.master_columns(), edits)
    except RefValidationError as exc:
        return invalid(exc)
    except ValueError as exc:
        return invalid(RefValidationError(f"Not a list of columns: {exc}"))
    load_types, types = lists.load_types().items, lists.equipment_packages().types
    deliverables = get_deliverables().list()
    impact = []
    for key, ch in changes.items():
        one = {key: ch}
        dropped = sum(rewrite_rows(t.rows, one)[1] for t in [*load_types, *types])
        names = [d.name for d in deliverables if d.source == "project" and d.type == LISTS[key].deliverable_type
                 and (rename_in(d.columns, ch) != d.columns or (d.filter_column and rename_in([d.filter_column], ch) != [d.filter_column]))]
        if ch.renames or ch.deletes or ch.added or ch.columns != lists.master_columns().of(key):
            impact.append(ListImpact(key=key, name=MASTER_NAMES[key], renames=ch.renames, deletes=ch.deletes, added=ch.added,
                                     cells_dropped=dropped, deliverables=names))
    if not dry_run:
        lists.save_master_columns(changes)
    return ColumnsSaved(view=_columns_view(), impact=impact, saved=not dry_run)
