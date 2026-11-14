# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Deliverables: the issued lists of a project (cable schedules, instrument lists, PLC I/O
lists, equipment lists, load lists), each taking its content from a generator's builds and
issued in lettered revisions (see workbench_core.deliverables)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from workbench_core.deliverables import (DELIVERABLE_TYPES, PANEL_TYPE, Deliverable, Revision, RevisionInfo, apply_filter,
                                         check_deliverable, compare, content_rows, next_letter, select_columns)
from workbench_core.keylists.master import MASTER_NAMES, master_columns
from workbench_core.generators.editable import BuildInfo, input_hash
from workbench_core.generators.models import BuildResult, BuildStats, ChangeReport
from workbench_core.generators.xlsx_export import csv_bytes, export_name, xlsx_bytes
from workbench_core.keylists.distribution_panels import PANEL_COLUMNS, PANEL_DIFF_KEY, flatten, summary_lines
from workbench_core.keylists.loadgen import BY_TYPE, generate, load_list_columns, missing_load_types
from workbench_core.refdata import RefValidationError

from .exporting import save_to
from . import identity
from .refdata_api import invalid
from .storage import InUse, NotFound, get_deliverables, get_generators, get_keylists

router = APIRouter(prefix="/api/deliverables", tags=["deliverables"])
MEDIA = {"csv": "text/csv", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}


class GeneratorChoice(BaseModel):
    id: str
    name: str
    columns: list[str]  # the output's columns (for the filter)
    builds: int


class Summary(BaseModel):
    deliverable: Deliverable
    generator: str  # its name ("" if it is gone)
    latest: RevisionInfo | None = None
    revisions: int = 0


class PanelChoice(BaseModel):
    id: str
    tag: str
    title: str


class Overview(BaseModel):
    types: list[str]
    deliverables: list[Summary]
    generators: list[GeneratorChoice]
    project_columns: dict[str, list[str]]  # deliverable type -> the columns of its Project Load List output
    panels: list[PanelChoice] = Field(default_factory=list)  # the Distribution Panels list (for a Distribution Panel)


class Current(BaseModel):
    """What issuing now would freeze: the generator's latest build through the filter."""
    source: str = "generator"  # "project": generated now from the Project Load List and the load types
    warnings: list[str] = Field(default_factory=list)
    summary: list[tuple[str, str | int | float | None]] = Field(default_factory=list)  # a panel's header block
    build: BuildInfo | None = None
    stale: bool = False  # the generator was changed after that build
    rows: int = 0
    next_letter: str
    changes: ChangeReport | None = None  # against the latest revision (None: there is none)
    problem: str | None = None  # why nothing can be issued (no build, the filter's column is gone)
    result: BuildResult | None = None


class Detail(BaseModel):
    deliverable: Deliverable
    generator: str
    revisions: list[RevisionInfo]  # newest first
    builds: list[BuildInfo]  # of the generator, newest first
    current: Current


def _columns(rid: str) -> list[str]:
    gen = get_generators().get(rid).generator
    return [gen.id_column] + [c.name for c in gen.output_columns]


def _get(did: str) -> Deliverable:
    try:
        return get_deliverables().get(did)
    except NotFound as exc:
        raise HTTPException(404, "That deliverable no longer exists.") from exc


PROJECT = "Project Master Load List"
PANELS = "Distribution Panels"
Lines = list[tuple[str, str | int | float | None]]


def _source_name(d: Deliverable, generators: dict[str, str], panels: dict[str, str]) -> str:
    if d.source == "panel":
        return f"{PANELS}: {panels[d.panel_id]}" if d.panel_id in panels else ""
    if d.source == "project":  # its Project Master list, or the Project Load List
        spec = BY_TYPE.get(d.type)
        return MASTER_NAMES[spec.key] if spec and spec.templated else PROJECT
    return generators.get(d.generator_id, "")


def _panel_tags() -> dict[str, str]:
    return {p.id: p.tag for p in get_keylists().distribution_panels().panels}


def _panel(d: Deliverable) -> tuple[BuildResult, str, list[str], str | None, Lines]:
    """A panel-source deliverable's content, worked out now: (result, diff key, warnings, problem,
    the header block). The problem (the panel is gone, or has nothing on it) stops it being issued."""
    from .distribution_panels_api import schedule_of  # imported late: it runs the imports

    panel, schedule = schedule_of(d.panel_id)
    if panel is None or schedule is None:
        empty = BuildResult(header=list(PANEL_COLUMNS), rows=[], stats=BuildStats())
        return empty, PANEL_DIFF_KEY, [], "Its distribution panel no longer exists. Choose another.", []
    problem = None if panel.entries else f"{schedule.tag} has no circuits yet. Place them in Distribution Panels first."
    return flatten(schedule), PANEL_DIFF_KEY, schedule.findings, problem, summary_lines(panel, schedule)


def _generated(d: Deliverable) -> tuple[BuildResult, str, list[str], str | None, Lines]:
    """The content of a deliverable that isn't a generator's build."""
    return _panel(d) if d.source == "panel" else (*_project(d), [])


def _project(d: Deliverable) -> tuple[BuildResult, str, list[str], str | None]:
    """A project-source deliverable's content, worked out now: (result, diff key, warnings, problem).
    A Cable Schedule, Equipment List, Instrument List or PLC I/O List is its Project Master list
    (the Power and the Instrument generator together); a Load List is the Project Load List.
    The problem (loads with no load type) stops it being issued."""
    from .loadlist_api import current_rows  # imported late: it runs the imports
    from .master_api import master_of

    spec = BY_TYPE[d.type]
    if spec.templated:
        result, warnings, missing = master_of(spec.key)
        empty = "Its project master list has no rows yet: nothing comes from the Load List or the Instrument Runsheet."
    else:
        lists = get_keylists()
        rows, _, _ = current_rows()
        types = {t.id: t for t in lists.load_types().items}
        areas = {n.id: (n.tag, n.description) for n in lists.plant_areas().nodes}
        warnings = []
        result = generate(spec.key, rows, types, areas, lists.cable_types().items, warnings, load_fields=lists.load_fields())
        missing = missing_load_types(rows, types)
        empty = "The Load List has no loads yet."
    problem = None
    if missing:
        problem = (f"{len(missing)} load(s) in the Load List have no load type: {', '.join(missing[:12])}"
                   + (f" and {len(missing) - 12} more" if len(missing) > 12 else "") + ". Allocate them first.")
    elif not result.rows:
        problem = empty
    return result, spec.diff_key, warnings, problem


def _content_columns(d: Deliverable) -> tuple[list[str], str]:
    """(the columns of a project-source deliverable's content, the column revisions are compared by)."""
    spec = BY_TYPE[d.type]
    lists = get_keylists()
    if spec.templated:
        return master_columns(spec.key, lists.master_columns().of(spec.key)), spec.diff_key
    return [c for c, _ in load_list_columns(lists.load_fields())], spec.diff_key


def _checked(d: Deliverable) -> Deliverable:
    gens = {g.id for g in get_generators().list()}
    if d.type == PANEL_TYPE:
        return check_deliverable(d, get_deliverables().list(), gens, list(PANEL_COLUMNS), set(_panel_tags()), key_column=PANEL_DIFF_KEY)
    if d.source == "project":
        columns, key = _content_columns(d)
        return check_deliverable(d, get_deliverables().list(), gens, columns, key_column=key)
    columns = _columns(d.generator_id) if d.generator_id in gens else None
    key = get_generators().get(d.generator_id).generator.config.diff_key if d.generator_id in gens else ""
    return check_deliverable(d, get_deliverables().list(), gens, columns, key_column=key)


@router.get("", response_model=Overview)
def overview() -> Overview:
    store, gens = get_deliverables(), get_generators()
    names = {g.id: g.name for g in gens.list()}
    revs: dict[str, list[RevisionInfo]] = {}
    for r in store.revisions():
        revs.setdefault(r.deliverable_id, []).append(r)  # newest first
    panels = get_keylists().distribution_panels().panels
    tags = {p.id: p.tag for p in panels}
    cols = get_keylists().master_columns()
    items = [Summary(deliverable=d, generator=_source_name(d, names, tags),
                     latest=(revs.get(d.id) or [None])[0],
                     revisions=len(revs.get(d.id, []))) for d in store.list()]
    items.sort(key=lambda s: (DELIVERABLE_TYPES.index(s.deliverable.type), s.deliverable.name.casefold()))
    return Overview(types=DELIVERABLE_TYPES, deliverables=items, generators=[
        GeneratorChoice(id=g.id, name=g.name, columns=_columns(g.id), builds=len(gens.list_builds(g.id))) for g in gens.list()],
        project_columns={t: (master_columns(x.key, cols.of(x.key)) if x.templated else [c for c, _ in load_list_columns(get_keylists().load_fields())]) for t, x in BY_TYPE.items()}
        | {PANEL_TYPE: list(PANEL_COLUMNS)},
        panels=[PanelChoice(id=p.id, tag=p.tag, title=p.title) for p in panels])


class DeliverableBody(BaseModel):
    type: str
    name: str
    doc_number: str = ""
    doc_title: str = ""
    source: Literal["generator", "project", "panel"] = "generator"
    generator_id: str = ""
    panel_id: str = ""
    filter_column: str = ""
    filter_values: list[str] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)  # the columns to keep, in order (empty: all)


def _from_body(body: DeliverableBody, did: str | None = None) -> Deliverable:
    if body.type not in DELIVERABLE_TYPES:
        raise RefValidationError("Choose the type of deliverable.", {"type": "Choose a type"})
    data = body.model_dump()
    return Deliverable(**data) if did is None else Deliverable(id=did, **data)


@router.post("", response_model=Deliverable)
def create(body: DeliverableBody):
    try:
        return get_deliverables().save(_checked(_from_body(body)), create=True)
    except RefValidationError as exc:
        return invalid(exc)


def _current(d: Deliverable, with_rows: bool) -> Current:
    store, gens = get_deliverables(), get_generators()
    letter = next_letter([r.letter for r in store.revisions(d.id)])
    if d.source != "generator":
        result, diff_key, warnings, problem, summary = _generated(d)
        try:
            result = select_columns(apply_filter(result, d.filter_column, d.filter_values), d.columns)
        except RefValidationError as exc:
            return Current(source=d.source, next_letter=letter, problem=exc.message)
        return Current(source=d.source, warnings=warnings, summary=summary, rows=content_rows(result), next_letter=letter,
                       problem=problem, changes=compare(store.latest(d.id), result, diff_key), result=result if with_rows else None)
    try:
        rec = gens.get(d.generator_id)
    except NotFound:
        return Current(next_letter=letter, problem="Its generator no longer exists. Choose another generator.")
    build = gens.latest_build(d.generator_id)
    if build is None:
        return Current(next_letter=letter, problem=f"{rec.name} has not been built yet. Build it in Generators first.")
    stale = build.info.input_hash != input_hash(rec.generator, gens.tables(rec.id), build.info.run_from, build.info.run_up_to)
    try:
        result = select_columns(apply_filter(build.result, d.filter_column, d.filter_values), d.columns)
    except RefValidationError as exc:
        return Current(build=build.info, stale=stale, next_letter=letter, problem=exc.message)
    changes = compare(store.latest(d.id), result, rec.generator.config.diff_key)
    return Current(build=build.info, stale=stale, rows=content_rows(result), next_letter=letter, changes=changes,
                   result=result if with_rows else None)


@router.get("/{did}", response_model=Detail)
def detail(did: str, rows: bool = False) -> Detail:
    """`rows=true` includes the current content's rows (they can be large)."""
    d = _get(did)
    gens = get_generators()
    try:
        name, builds = gens.get(d.generator_id).name, gens.list_builds(d.generator_id)
    except NotFound:
        name, builds = _source_name(d, {}, _panel_tags()), []
    return Detail(deliverable=d, generator=name, revisions=get_deliverables().revisions(did), builds=builds,
                  current=_current(d, rows))


@router.put("/{did}", response_model=Deliverable)
def update(did: str, body: DeliverableBody):
    _get(did)
    try:
        return get_deliverables().save(_checked(_from_body(body, did)))
    except RefValidationError as exc:
        return invalid(exc)


@router.delete("/{did}")
def delete(did: str):
    _get(did)
    try:
        get_deliverables().delete(did)
    except InUse as exc:
        return invalid(RefValidationError(f"This deliverable can't be deleted: {exc} Withdraw them first, latest first."))
    return {"status": "deleted"}


# -- revisions ---------------------------------------------------------------------------------

class IssueBody(BaseModel):
    description: str = ""
    build_id: str | None = None  # an earlier build of the generator; default: its latest


@router.post("/{did}/revisions", response_model=RevisionInfo)
def issue(did: str, body: IssueBody):
    d = _get(did)
    summary: Lines = []
    if d.source != "generator":
        source, diff_key, _, problem, summary = _generated(d)
        if problem:
            return invalid(RefValidationError(problem))
        build_seq = 0
    else:
        gens = get_generators()
        try:
            rec = gens.get(d.generator_id)
        except NotFound:
            return invalid(RefValidationError("Its generator no longer exists. Choose another generator."))
        try:
            build = gens.get_build(body.build_id) if body.build_id else gens.latest_build(d.generator_id)
        except NotFound:
            build = None
        if build is None or build.info.generator_id != d.generator_id:
            return invalid(RefValidationError(f"There is no build of {rec.name} to issue. Build it in Generators first."))
        source, diff_key, build_seq = build.result, rec.generator.config.diff_key, build.info.seq
    try:
        result = select_columns(apply_filter(source, d.filter_column, d.filter_values), d.columns)
    except RefValidationError as exc:
        return invalid(exc)

    def make(letter: str, previous: Revision | None) -> Revision:
        changes = compare(previous, result, diff_key)
        info = RevisionInfo(deliverable_id=d.id, letter=letter, issued_at=datetime.now(timezone.utc),
                            issued_by=identity.current().user, description=body.description.strip(),
                            build_seq=build_seq, rows=content_rows(result),
                            added=changes.added if changes else None, removed=changes.removed if changes else None,
                            changed=changes.changed if changes else None)
        return Revision(info=info, result=result, diff_key=diff_key, doc_number=d.doc_number, doc_title=d.doc_title,
                        filter_column=d.filter_column, filter_values=d.filter_values, changes=changes, summary=summary)

    return get_deliverables().issue(d, make).info


def _revision(rid: str) -> Revision:
    try:
        return get_deliverables().revision(rid)
    except NotFound as exc:
        raise HTTPException(404, "That revision no longer exists.") from exc


@router.get("/revisions/{rid}", response_model=Revision)
def get_revision(rid: str) -> Revision:
    return _revision(rid)


class DescriptionBody(BaseModel):
    description: str


@router.put("/revisions/{rid}", response_model=RevisionInfo)
def amend(rid: str, body: DescriptionBody) -> RevisionInfo:
    """Only the description of an issued revision can change."""
    _revision(rid)
    return get_deliverables().set_description(rid, body.description)


class WithdrawBody(BaseModel):
    reason: str


@router.post("/revisions/{rid}/withdraw")
def withdraw(rid: str, body: WithdrawBody):
    """Withdraw the latest revision of a deliverable (its letter is used by the next issue)."""
    _revision(rid)
    if not body.reason.strip():
        return invalid(RefValidationError("Say why the revision is withdrawn.", {"reason": "Required"}))
    try:
        info = get_deliverables().withdraw(rid, body.reason)
    except InUse as exc:
        return invalid(RefValidationError(str(exc)))
    return {"status": "withdrawn", "letter": info.letter}


class Comparison(BaseModel):
    """What changed from one issued revision (`old`) to a later one (`new`)."""
    old: RevisionInfo
    new: RevisionInfo
    changes: ChangeReport


def _compared(rev: Revision, against: str) -> Comparison | None:
    """`rev` compared with another revision of its deliverable: `against` is that revision's id,
    or "previous" for the one issued before it (None when `rev` is the first). The earlier of
    the two is the old one, whichever was asked for first."""
    if against == "previous":
        earlier = [r for r in get_deliverables().revisions(rev.info.deliverable_id) if r.issued_at < rev.info.issued_at]
        if not earlier:
            return None
        other = _revision(max(earlier, key=lambda r: r.issued_at).id)
    else:
        other = _revision(against)
    if other.info.deliverable_id != rev.info.deliverable_id:
        raise HTTPException(400, "Those are revisions of two different deliverables.")
    if other.info.id == rev.info.id:
        raise HTTPException(400, "Choose another revision to compare with.")
    old, new = sorted((rev, other), key=lambda r: r.info.issued_at)
    return Comparison(old=old.info, new=new.info, changes=compare(old, new.result, new.diff_key))


@router.get("/revisions/{rid}/compare", response_model=Comparison)
def compare_revisions(rid: str, against: str = Query(..., min_length=1)) -> Comparison:
    """What changed between any two revisions of a deliverable (not only one and the one before)."""
    c = _compared(_revision(rid), against)
    if c is None:
        raise HTTPException(400, "That is the first revision: there is none before it.")
    return c


class ExportBody(BaseModel):
    format: Literal["xlsx", "csv"] = "xlsx"
    path: str | None = None  # desktop: chosen in a Save As dialog
    #: .xlsx only: add a "Changes" sheet against this revision (its id, or "previous").
    changes_against: str | None = None


def _export_config(rev: Revision, name: str):
    from workbench_core.generators.models import GeneratorConfig
    return GeneratorConfig(doc_number=rev.doc_number or name, doc_title=rev.doc_title or (name if rev.doc_number else ""),
                           doc_revision=rev.info.letter)


@router.get("/revisions/{rid}/name")
def export_file_name(rid: str, format: Literal["xlsx", "csv"] = "xlsx") -> dict[str, str]:
    rev = _revision(rid)
    return {"name": export_name(_export_config(rev, _get(rev.info.deliverable_id).name), "", rev.info.issued_at, f".{format}")}


@router.post("/revisions/{rid}/export")
def export_revision(rid: str, body: ExportBody, request: Request):
    # JSON only: forces a CORS preflight, so a cross-site page can't trigger a file write.
    if not request.headers.get("content-type", "").startswith("application/json"):
        raise HTTPException(415, "Expected application/json")
    rev = _revision(rid)
    cfg = _export_config(rev, _get(rev.info.deliverable_id).name)
    if body.format == "xlsx":
        c = _compared(rev, body.changes_against) if body.changes_against else None
        data = xlsx_bytes(rev.result, cfg, f"{rev.info.build_seq}", rev.summary, changes=c.changes if c else None,
                          changes_label=f"Rev {c.new.letter} compared with Rev {c.old.letter}" if c else "", key_name=rev.diff_key)
    else:
        data = csv_bytes(rev.result, cfg.date_format)
    if body.path is None:
        name = export_name(cfg, "", rev.info.issued_at, f".{body.format}")
        return Response(data, media_type=MEDIA[body.format], headers={"Content-Disposition": f'attachment; filename="{name}"'})
    return save_to(body.path, data, f".{body.format}")
