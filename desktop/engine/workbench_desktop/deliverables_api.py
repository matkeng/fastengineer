# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Deliverables: the issued lists of a project (cable schedules, instrument lists, PLC I/O
lists, equipment lists, load lists), each taking its content from a generator's builds and
issued in lettered revisions (see workbench_core.deliverables)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from workbench_core.deliverables import (DELIVERABLE_TYPES, Deliverable, Revision, RevisionInfo, apply_filter,
                                         check_deliverable, compare, content_rows, next_letter)
from workbench_core.generators.editable import BuildInfo, input_hash
from workbench_core.generators.models import BuildResult, ChangeReport
from workbench_core.generators.xlsx_export import csv_bytes, export_name, xlsx_bytes
from workbench_core.keylists.loadgen import BY_TYPE, generate, missing_load_types
from workbench_core.refdata import RefValidationError

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


class Overview(BaseModel):
    types: list[str]
    deliverables: list[Summary]
    generators: list[GeneratorChoice]
    project_columns: dict[str, list[str]]  # deliverable type -> the columns of its Project Load List output


class Current(BaseModel):
    """What issuing now would freeze: the generator's latest build through the filter."""
    source: str = "generator"  # "project": generated now from the Project Load List and the load types
    warnings: list[str] = Field(default_factory=list)
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


PROJECT = "Project Load List"


def _project(d: Deliverable) -> tuple[BuildResult, str, list[str], str | None]:
    """A project-source deliverable's content, generated now: (result, diff key, warnings, problem).
    The problem (loads with no load type) stops it being issued."""
    from .loadlist_api import current_rows  # imported late: it runs the imports

    lists = get_keylists()
    spec = BY_TYPE[d.type]
    rows, _, _ = current_rows()
    types = {t.id: t for t in lists.load_types().items}
    areas = {n.id: (n.tag, n.description) for n in lists.plant_areas().nodes}
    result = generate(spec.key, rows, types, areas)
    warnings = []
    if result.unresolved_count:
        warnings.append(f"{result.unresolved_count} tag(s) in the load types' rows match nothing and were left as they are: "
                        + ", ".join(result.unresolved_tokens[:10]))
    missing = missing_load_types(rows, types)
    problem = None
    if missing:
        problem = (f"{len(missing)} load(s) in the Load List have no load type: {', '.join(missing[:12])}"
                   + (f" and {len(missing) - 12} more" if len(missing) > 12 else "") + ". Allocate them first.")
    elif not any(r.status == "active" for r in rows):
        problem = "The Load List has no loads yet."
    return result, spec.diff_key, warnings, problem


def _checked(d: Deliverable) -> Deliverable:
    gens = {g.id for g in get_generators().list()}
    if d.source == "project":
        return check_deliverable(d, get_deliverables().list(), gens, list(BY_TYPE[d.type].columns))
    columns = _columns(d.generator_id) if d.generator_id in gens else None
    return check_deliverable(d, get_deliverables().list(), gens, columns)


@router.get("", response_model=Overview)
def overview() -> Overview:
    store, gens = get_deliverables(), get_generators()
    names = {g.id: g.name for g in gens.list()}
    revs: dict[str, list[RevisionInfo]] = {}
    for r in store.revisions():
        revs.setdefault(r.deliverable_id, []).append(r)  # newest first
    items = [Summary(deliverable=d, generator=PROJECT if d.source == "project" else names.get(d.generator_id, ""),
                     latest=(revs.get(d.id) or [None])[0],
                     revisions=len(revs.get(d.id, []))) for d in store.list()]
    items.sort(key=lambda s: (DELIVERABLE_TYPES.index(s.deliverable.type), s.deliverable.name.casefold()))
    return Overview(types=DELIVERABLE_TYPES, deliverables=items, generators=[
        GeneratorChoice(id=g.id, name=g.name, columns=_columns(g.id), builds=len(gens.list_builds(g.id))) for g in gens.list()],
        project_columns={t: list(x.columns) for t, x in BY_TYPE.items()})


class DeliverableBody(BaseModel):
    type: str
    name: str
    doc_number: str = ""
    doc_title: str = ""
    source: Literal["generator", "project"] = "generator"
    generator_id: str = ""
    filter_column: str = ""
    filter_values: list[str] = Field(default_factory=list)


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
    if d.source == "project":
        result, diff_key, warnings, problem = _project(d)
        try:
            result = apply_filter(result, d.filter_column, d.filter_values)
        except RefValidationError as exc:
            return Current(source="project", next_letter=letter, problem=exc.message)
        return Current(source="project", warnings=warnings, rows=content_rows(result), next_letter=letter, problem=problem,
                       changes=compare(store.latest(d.id), result, diff_key), result=result if with_rows else None)
    try:
        rec = gens.get(d.generator_id)
    except NotFound:
        return Current(next_letter=letter, problem="Its generator no longer exists. Choose another generator.")
    build = gens.latest_build(d.generator_id)
    if build is None:
        return Current(next_letter=letter, problem=f"{rec.name} has not been built yet. Build it in Generators first.")
    stale = build.info.input_hash != input_hash(rec.generator, gens.tables(rec.id), build.info.run_from, build.info.run_up_to)
    try:
        result = apply_filter(build.result, d.filter_column, d.filter_values)
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
        name, builds = (PROJECT if d.source == "project" else ""), []
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
    if d.source == "project":
        source, diff_key, _, problem = _project(d)
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
        result = apply_filter(source, d.filter_column, d.filter_values)
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
                        filter_column=d.filter_column, filter_values=d.filter_values, changes=changes)

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


class ExportBody(BaseModel):
    format: Literal["xlsx", "csv"] = "xlsx"
    path: str | None = None  # desktop: chosen in a Save As dialog


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
    data = xlsx_bytes(rev.result, cfg, f"{rev.info.build_seq}") if body.format == "xlsx" else csv_bytes(rev.result, cfg.date_format)
    if body.path is None:
        name = export_name(cfg, "", rev.info.issued_at, f".{body.format}")
        return Response(data, media_type=MEDIA[body.format], headers={"Content-Disposition": f'attachment; filename="{name}"'})
    target = Path(body.path)
    if target.suffix.lower() != f".{body.format}":
        target = target.with_suffix(f".{body.format}")
    try:
        target.write_bytes(data)
    except OSError as exc:
        raise HTTPException(409, f"Could not write {target}: {exc.strerror or exc}. Is it open in another program?") from exc
    return {"path": str(target)}
