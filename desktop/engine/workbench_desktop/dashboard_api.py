# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""One summary of everything stored, for the dashboard (read-only; built in one pass)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .excel_api import store as workbooks
from .storage import get_deliverables, get_generators, get_keylists, get_loadlist, get_ref, get_store
from . import symbols_api  # looked up per request, so tests can stub its OCR provider

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

RECENT = 15
RUNS = 10


class Event(BaseModel):
    kind: str  # run | drawing | revision | recipe | enum | tree | table | generator | build
    section: str  # the app section to open: symbols | mel | ref | generators
    id: str
    title: str
    detail: str = ""
    at: datetime


class RunBar(BaseModel):
    id: str
    at: datetime
    template: int = 0
    text_scan: int = 0
    status: str = "done"


class Counts(BaseModel):
    libraries: int = 0
    templates: int = 0
    drawings: int = 0
    pages: int = 0
    pages_unanalysed: int = 0
    runs: int = 0
    latest_tags: int | None = None
    latest_run_at: datetime | None = None
    recipes: int = 0
    revisions: int = 0
    latest_revision_at: datetime | None = None
    enums: int = 0
    trees: int = 0
    tables: int = 0
    rows: int = 0
    plant_areas: int = 0
    equipment_packages: int = 0
    equipment_types: int = 0
    load_types: int = 0
    load_list_rows: int = 0
    equipment_codes: int = 0
    instrument_codes: int = 0
    eel_items: int = 0
    distribution_panels: int = 0
    instrument_runsheet_rows: int = 0
    drawings_listed: int = 0
    documents_listed: int = 0
    deliverables: int = 0
    deliverable_revisions: int = 0
    generators: int = 0
    gen_builds: int = 0
    plc_panels: int = 0
    plc_cards: int = 0
    latest_build_at: datetime | None = None
    open_workbooks: int = 0


class Storage(BaseModel):
    data_dir: str
    database_bytes: int = 0
    drawings_bytes: int = 0
    page_images: int = 0
    ocr_available: bool = False
    ocr_engine: str | None = None
    ocr_reason: str | None = None


class Dashboard(BaseModel):
    counts: Counts
    recent: list[Event] = Field(default_factory=list)
    runs: list[RunBar] = Field(default_factory=list)
    storage: Storage


def _size(path: Path) -> tuple[int, int]:
    """(total bytes, number of page PNGs) under a folder."""
    total = pngs = 0
    if path.exists():
        for p in path.rglob("*"):
            if p.is_file():
                total += p.stat().st_size
                pngs += p.name.startswith("page-") and p.suffix == ".png"
    return total, pngs


def _ts(value) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


@router.get("", response_model=Dashboard)
def dashboard() -> Dashboard:
    c = Counts(open_workbooks=len(workbooks._items))
    events: list[Event] = []

    # List imports and their revisions
    st = get_store()
    for r in st.list_recipes():
        c.recipes += 1
        c.revisions += r["revisions"] or 0
        at = _ts(r["updated_at"])
        if at:
            events.append(Event(kind="recipe", section="mel", id=r["id"], title=r["name"],
                                detail=f"{r['target']} import saved", at=at))
        for v in st.list_revisions(r["id"]):
            events.append(Event(kind="revision", section="mel", id=r["id"], title=f"{r['name']}: rev {v.rev}",
                                detail=f"{v.file_name} · {v.num_rows} rows", at=v.uploaded_at))
            if c.latest_revision_at is None or v.uploaded_at > c.latest_revision_at:
                c.latest_revision_at = v.uploaded_at

    # Lists, trees and tables: they have no section in the app any more, so they are counted
    # (the engine still keeps them) but are not in the recent activity.
    ref = get_ref()
    counts = ref.row_counts()
    c.enums, c.trees = len(ref.enums()), len(ref.trees())
    for t in ref.tables():
        c.tables += 1
        c.rows += counts.get(t.id, 0)

    c.plant_areas = len(get_keylists().plant_areas().nodes)
    packages = get_keylists().equipment_packages()
    c.equipment_packages, c.equipment_types = len(packages.items), len(packages.types)
    c.load_types = len(get_keylists().load_types().items)
    c.equipment_codes = len(get_keylists().code_list("equipment-codes").items)
    c.instrument_codes = len(get_keylists().code_list("instrument-codes").items)
    c.eel_items = len(get_keylists().eel().items)
    c.distribution_panels = len(get_keylists().distribution_panels().panels)
    c.instrument_runsheet_rows = len(get_keylists().instrument_runsheet().rows)
    c.drawings_listed = len(get_keylists().drawing_list().items)
    c.documents_listed = len(get_keylists().document_list().items)
    dl = get_deliverables()
    names = {d.id: d.name for d in dl.list()}
    c.deliverables = len(names)
    for r in dl.revisions():
        c.deliverable_revisions += 1
        events.append(Event(kind="revision_issued", section="deliverables", id=r.deliverable_id,
                            title=f"{names.get(r.deliverable_id, '')}: Rev {r.letter} issued",
                            detail=f"{r.rows} rows" + (f" · {r.description}" if r.description else ""), at=r.issued_at))
    c.load_list_rows = sum(r.status == "active" for r in get_loadlist().rows())

    # Symbol detection
    sym = symbols_api.store()
    libs = {lib.id: lib.name for lib in sym.libraries()}
    c.libraries = len(libs)
    c.templates = len(sym.templates())
    analysed: set[tuple[str, int]] = set()
    with sym._lock:
        for doc_id, page in sym._db.execute("SELECT doc_id, page FROM sym_results").fetchall():
            analysed.add((doc_id, page))
    for d in sym.drawings():
        c.drawings += 1
        c.pages += len(d.pages)
        c.pages_unanalysed += sum((d.id, p.n) not in analysed for p in d.pages)
        if d.uploaded_at:
            events.append(Event(kind="drawing", section="symbols", id=d.id, title=d.file_name,
                                detail=f"{len(d.pages)} page(s) · {libs.get(d.library_id, '?')}", at=d.uploaded_at))
    bars: list[RunBar] = []
    runs = sym.runs()  # newest first
    c.runs = len(runs)
    for i, run in enumerate(runs):
        at = run.finished_at or run.started_at
        if at is None:
            continue
        if run.status == "done" and c.latest_tags is None:
            c.latest_tags, c.latest_run_at = run.tag_count, at
        events.append(Event(kind="run", section="symbols", id=run.id, title=f"Analysis of {len(run.doc_ids)} drawing(s)",
                            detail=f"{run.tag_count} tags" if run.status == "done" else run.status, at=at))
        if len(bars) < RUNS and run.status in ("done", "cancelled"):
            _, sheets = sym.get_run(run.id)
            seen: dict[str, str] = {}
            for sh in sheets:
                for tag in sh["result"]["tags"]:
                    if seen.get(tag["tag"]) != "template":  # a tag found by a template counts as template
                        seen[tag["tag"]] = tag["source"]
            bars.append(RunBar(id=run.id, at=at, status=run.status,
                               template=sum(v == "template" for v in seen.values()),
                               text_scan=sum(v != "template" for v in seen.values())))

    # Deliverable generators and their builds
    gens = get_generators()
    names = {}
    for g in gens.list():
        c.generators += 1
        names[g.id] = g.name
        if g.updated_at:
            events.append(Event(kind="generator", section="generators", id=g.id, title=g.name,
                                detail=f"generator · {g.runs} runs · {g.templates} templates", at=g.updated_at))
    plc = get_keylists().plc()
    c.plc_panels = len(plc.systems)
    c.plc_cards = sum(1 for s in plc.systems for r in s.racks for x in r.cards if x is not None)
    for b in gens.all_builds():
        c.gen_builds += 1
        if c.latest_build_at is None or b.created_at > c.latest_build_at:
            c.latest_build_at = b.created_at
        diff = "" if b.added is None else f" · +{b.added} −{b.removed} ~{b.changed}"
        events.append(Event(kind="build", section="generators", id=b.generator_id,
                            title=f"{names.get(b.generator_id, '?')}: build {b.seq}",
                            detail=f"{b.stats.rows_written} rows{diff}", at=b.created_at))

    db = st.path
    drawings_bytes, pngs = _size(sym.root)
    provider, why = symbols_api.ocr_provider()
    storage = Storage(data_dir=str(db.parent), database_bytes=db.stat().st_size if db.exists() else 0,
                      drawings_bytes=drawings_bytes, page_images=pngs, ocr_available=provider is not None,
                      ocr_engine=getattr(provider, "name", None), ocr_reason=why)
    events.sort(key=lambda e: e.at, reverse=True)
    return Dashboard(counts=c, recent=events[:RECENT], runs=list(reversed(bars)), storage=storage)
