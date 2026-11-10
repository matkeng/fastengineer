# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""One summary of everything stored, for the dashboard (read-only; built in one pass)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .excel_api import store as workbooks
from .storage import get_generators, get_keylists, get_ref, get_store
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

    # Lists & tables
    ref = get_ref()
    counts = ref.row_counts()
    for e in ref.enums().values():
        c.enums += 1
        if e.updated_at:
            events.append(Event(kind="enum", section="ref", id=e.id, title=e.name, detail=f"list · {len(e.items)} items",
                                at=e.updated_at))
    for tr in ref.trees():
        c.trees += 1
        if tr.updated_at:
            events.append(Event(kind="tree", section="ref", id=tr.id, title=tr.name, detail=f"tree · {len(tr.nodes)} items",
                                at=tr.updated_at))
    for t in ref.tables():
        c.tables += 1
        c.rows += counts.get(t.id, 0)
        if t.updated_at:
            events.append(Event(kind="table", section="ref", id=t.id, title=t.name,
                                detail=f"table · {counts.get(t.id, 0)} rows", at=t.updated_at))

    c.plant_areas = len(get_keylists().plant_areas().nodes)
    c.equipment_packages = len(get_keylists().equipment_packages().items)

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
    c.plc_panels, c.plc_cards = gens.hardware_counts()
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
