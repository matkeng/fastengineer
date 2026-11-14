# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Symbol detection endpoints over workbench_core.symbols.

Rendering and analysis runs go through one background worker thread, so the UI stays
responsive and jobs never compete for CPU; the UI polls their status. The P&ID example
library is added the first time the store is used."""

from __future__ import annotations

import base64
import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from workbench_core.refdata import RefValidationError
from workbench_core.symbols import (
    Drawing,
    Library,
    PageInfo,
    PageOverride,
    PageResult,
    PageReview,
    Rejection,
    RunInfo,
    SheetResult,
    Symbol,
    Template,
    Word,
    analyse_page,
    apply_review,
    choose_words,
    tags_table,
)
from workbench_core.symbols import ocr as ocr_mod
from workbench_core.symbols.export import tags_csv, tags_xlsx
from workbench_core.symbols.match import _iou, locate_near, locate_symbols, prepare
from workbench_core.symbols.render import PdfError, decode_gray, encode_png, page_count, render_pages
from workbench_core.symbols.pipeline import REVIEW_IOU
from workbench_core.symbols.tags import apply_exclusion, check_format, compile_pattern, format_tag, group_names, resolve_points
from workbench_core.symbols.templates import crop, effective_mask, erase_words, trim_box

from . import identity
from .storage import InUse, NotFound, SymbolStore, get_symbols

router = APIRouter(prefix="/api/symbols", tags=["symbol detection"])

MAX_UPLOAD = 200 * 1024 * 1024
LIBRARY_FORMAT = "drawing-workbench-symbol-library"
_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="symbols")
_cancel: set[str] = set()
_seed_lock = threading.Lock()
ocr_provider = ocr_mod.default_provider  # tests replace this


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _nf(what: str) -> HTTPException:
    return HTTPException(404, f"That {what} no longer exists.")


def _invalid(message: str, fields: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": message, "fields": fields or {}})


def store() -> SymbolStore:
    """The symbol store, with the P&ID example added the very first time."""
    st = get_symbols()
    if not st.seeded():
        with _seed_lock:
            if not st.seeded():
                from workbench_core.symbols.starter import STARTER_LIBRARY
                import_library(st, STARTER_LIBRARY)
                st.mark_seeded()
    return st


def _drawing(doc_id: str) -> Drawing:
    try:
        return store().get_drawing(doc_id)
    except NotFound as exc:
        raise _nf("drawing") from exc


def _template(template_id: str) -> Template:
    try:
        return store().get_template(template_id)
    except NotFound as exc:
        raise _nf("template") from exc


def _library(library_id: str) -> Library:
    try:
        return store().get_library(library_id)
    except NotFound as exc:
        raise _nf("library") from exc


def _page(d: Drawing, n: int) -> PageInfo:
    if d.status != "ready":
        raise HTTPException(409, "The drawing is still being prepared." if d.status == "rendering" else (d.error or "The drawing could not be read."))
    if not 1 <= n <= len(d.pages):
        raise HTTPException(404, f"The drawing has {len(d.pages)} page(s).")
    return d.pages[n - 1]


# -- libraries ----------------------------------------------------------------------

def _check_library(lib: Library) -> dict[str, str]:
    f: dict[str, str] = {}
    if not lib.name.strip():
        f["name"] = "Give the library a name."
    try:
        rx = compile_pattern(lib.tag_pattern)
    except ValueError as exc:
        f["tag_pattern"] = str(exc)
        rx = None
    if lib.tag_format.strip():
        if rx is None and "tag_pattern" not in f:
            f["tag_format"] = "A format needs a tag pattern with named groups to fill it."
        elif rx is not None:
            err = check_format(lib.tag_format, rx.groupindex)
            if err:
                f["tag_format"] = err
    if lib.min_pdf_words < 0:
        f["min_pdf_words"] = "0 or more."
    if not 0.05 <= lib.default_threshold <= 1:
        f["default_threshold"] = "Between 0.05 and 1."
    for a in lib.exclusion.areas:
        if len(a) != 4 or not all(0 <= v <= 1 for v in a):
            f["exclusion"] = "Ignored areas are page fractions between 0 and 1."
    return f


def import_library(st: SymbolStore, data: dict, name: str | None = None) -> tuple[Library, list[Template]]:
    """Create a library (and its templates) from a library file."""
    if data.get("format") != LIBRARY_FORMAT or not isinstance(data.get("library"), dict):
        raise HTTPException(400, "That file is not a symbol library exported from this app.")
    raw = dict(data["library"])
    for k in ("id", "created_at"):
        raw.pop(k, None)
    lib = Library(id=uuid.uuid4().hex, **{**raw, "name": st.unique_name(name or raw.get("name", "Library"))},
                  created_at=_now())
    fields = _check_library(lib)
    if fields:
        raise HTTPException(400, f"The library file has problems: {'; '.join(fields.values())}")
    st.save_library(lib, create=True)
    out = []
    for t in sorted(data.get("templates", []), key=lambda t: t.get("priority", 0)):
        t = dict(t)
        try:
            gray = decode_gray(base64.b64decode(t.pop("image_png")))
            mask = base64.b64decode(t.pop("mask_png")) if t.get("mask_png") else None
            t.pop("mask_png", None)
        except Exception as exc:
            raise HTTPException(400, f"Template '{t.get('desc', '?')}' has no readable image.") from exc
        view_png, view_words = t.pop("view_png", None), t.pop("view_words", None)
        try:
            view = (base64.b64decode(view_png), [Word.model_validate(w) for w in view_words or []]) if view_png else None
        except Exception:  # a view is only for show: a broken one is left out
            view = None
        for k in ("id", "width", "height", "priority", "library_id", "has_custom_mask"):
            t.pop(k, None)
        tpl = Template(id=uuid.uuid4().hex, library_id=lib.id, width=int(gray.shape[1]), height=int(gray.shape[0]), **t)
        out.append(st.add_template(tpl, encode_png(gray), mask))
        if view:
            st.set_template_view(tpl.id, *view)
    return lib, out


def export_library(st: SymbolStore, library_id: str) -> dict:
    lib = st.get_library(library_id)
    ts = []
    for t in st.templates(library_id):
        d = t.model_dump(exclude={"id", "library_id", "width", "height", "has_custom_mask"})
        d["image_png"] = base64.b64encode(st.template_image(t.id)).decode()
        mask = st.template_mask(t.id)
        if mask:
            d["mask_png"] = base64.b64encode(mask).decode()
        view = st.template_view(t.id)
        if view:
            d["view_png"] = base64.b64encode(view[0]).decode()
            d["view_words"] = [w.model_dump(mode="json") for w in view[1]]
        ts.append(d)
    return {"format": LIBRARY_FORMAT, "version": 2,
            "library": lib.model_dump(mode="json", exclude={"id", "created_at"}), "templates": ts}


class LibrarySummary(Library):
    templates: int = 0
    drawings: int = 0
    columns: list[str] = Field(default_factory=list)


@router.get("/libraries", response_model=list[LibrarySummary])
def list_libraries() -> list[LibrarySummary]:
    st = store()
    t_count: dict[str, int] = {}
    d_count: dict[str, int] = {}
    for t in st.templates():
        t_count[t.library_id] = t_count.get(t.library_id, 0) + 1
    for d in st.drawings():
        d_count[d.library_id] = d_count.get(d.library_id, 0) + 1
    out = []
    for lib in st.libraries():
        try:
            cols = group_names(lib)
        except ValueError:
            cols = []
        out.append(LibrarySummary(**lib.model_dump(), templates=t_count.get(lib.id, 0),
                                  drawings=d_count.get(lib.id, 0), columns=cols))
    return out


class NewLibrary(BaseModel):
    name: str
    copy_from: str | None = None  # duplicate an existing library (templates included)


@router.post("/libraries", response_model=Library)
def create_library(body: NewLibrary):
    st = store()
    if not body.name.strip():
        return _invalid("Give the library a name.", {"name": "Required."})
    if body.copy_from:
        _library(body.copy_from)
        return import_library(st, export_library(st, body.copy_from), body.name)[0]
    lib = Library(id=uuid.uuid4().hex, name=body.name.strip(), created_at=_now())
    try:
        return st.save_library(lib, create=True)
    except RefValidationError as exc:
        return _invalid(exc.message, exc.fields)


@router.post("/libraries/import", response_model=Library)
def import_library_file(body: dict) -> Library:
    return import_library(store(), body)[0]


@router.post("/libraries/restore-example", response_model=Library)
def restore_example() -> Library:
    """Add the P&ID example library again (as a new copy)."""
    from workbench_core.symbols.starter import STARTER_LIBRARY
    return import_library(store(), STARTER_LIBRARY)[0]


@router.get("/libraries/{library_id}", response_model=Library)
def get_library(library_id: str) -> Library:
    return _library(library_id)


@router.put("/libraries/{library_id}", response_model=Library)
def save_library(library_id: str, body: Library):
    old = _library(library_id)
    lib = body.model_copy(update={"id": library_id, "created_at": old.created_at})
    fields = _check_library(lib)
    if fields:
        return _invalid("Fix the highlighted fields.", fields)
    try:
        return store().save_library(lib)
    except RefValidationError as exc:
        return _invalid(exc.message, exc.fields)


@router.delete("/libraries/{library_id}")
def delete_library(library_id: str):
    try:
        store().delete_library(library_id)
    except InUse as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"status": "deleted"}


class SavePath(BaseModel):
    path: str | None = None  # desktop: chosen in a Save As dialog


def _write(path: str, data: bytes, suffix: str) -> dict[str, str]:
    target = Path(path)
    if target.suffix.lower() != suffix:
        target = target.with_suffix(suffix)
    try:
        target.write_bytes(data)
    except OSError as exc:
        raise HTTPException(409, f"Could not save {target.name}: {exc.strerror or exc}. Is it open in another program?") from exc
    return {"path": str(target)}


def _json_only(request: Request) -> None:
    # JSON only: forces a CORS preflight, so a cross-site page can't trigger a file write.
    if not request.headers.get("content-type", "").startswith("application/json"):
        raise HTTPException(415, "Expected application/json")


@router.post("/libraries/{library_id}/export")
def export_library_file(library_id: str, body: SavePath, request: Request):
    _json_only(request)
    _library(library_id)
    data = export_library(store(), library_id)
    return data if body.path is None else _write(body.path, json.dumps(data, indent=1).encode(), ".json")


# -- words ----------------------------------------------------------------------

def _load_words(path: Path) -> list[Word]:
    return [Word(**w) for w in json.loads(path.read_text())] if path.exists() else []


def page_words(st: SymbolStore, d: Drawing, n: int, gray, lib: Library) -> tuple[list[Word], str, list[str]]:
    """The words a page is analysed with: its text layer, or OCR (cached per page)."""
    pdf_words = _load_words(st.words_file(d.id, n))
    cached = st.words_file(d.id, n, "ocr")
    if (d.force_ocr or len(pdf_words) < lib.min_pdf_words) and cached.exists():
        return _load_words(cached), "ocr", []
    words, source, warnings = choose_words(gray, pdf_words, lib, d.force_ocr, ocr_provider)
    if source == "ocr":
        cached.write_text(json.dumps([w.model_dump() for w in words]))
    return words, source, warnings


def _gray(st: SymbolStore, doc_id: str, n: int):
    return decode_gray(st.page_png(doc_id, n).read_bytes())


def _custom_mask(st: SymbolStore, t: Template):
    png = st.template_mask(t.id) if t.mask_mode == "custom" else None
    return decode_gray(png) if png else None


def _prepared(st: SymbolStore, templates: list[Template]):
    return [prepare(t, decode_gray(st.template_image(t.id)), _custom_mask(st, t)) for t in templates]


# -- background jobs ---------------------------------------------------------------

def _render_job(doc_id: str) -> None:
    st = store()
    try:
        d = st.get_drawing(doc_id)
    except NotFound:
        return
    try:
        pages = []
        for p in render_pages((st.doc_dir(doc_id) / "source.pdf").read_bytes()):
            st.page_png(doc_id, p.n).write_bytes(p.png)
            st.words_file(doc_id, p.n).write_text(json.dumps([w.model_dump() for w in p.words]))
            pages.append(PageInfo(n=p.n, width_px=p.width_px, height_px=p.height_px, rotation=p.rotation,
                                  text_source="pdf" if p.words else "none", word_count=len(p.words)))
        d = d.model_copy(update={"pages": pages, "status": "ready", "error": None})
    except Exception as exc:  # report it on the drawing rather than losing it in a thread
        d = d.model_copy(update={"status": "error", "error": str(exc)})
    try:
        st.save_drawing(d)
    except NotFound:
        pass  # deleted while rendering


def analyse_one(st: SymbolStore, d: Drawing, n: int, lib: Library, prepared=None) -> PageResult:
    gray = _gray(st, d.id, n)
    words, source, warnings = page_words(st, d, n, gray, lib)
    if prepared is None:
        prepared = _prepared(st, st.templates(lib.id))
    region = None
    if source == "ocr":
        provider, _ = ocr_provider()
        region = getattr(provider, "read_region", None)
    res = analyse_page(n, gray, words, source, prepared, st.overrides(d.id, n), lib, region, st.review(d.id, n))
    res.warnings = warnings + res.warnings
    st.save_result(d.id, res)
    page = d.pages[n - 1]
    page.text_source, page.word_count = source, len(words)
    page.warnings = warnings
    return res


def _run_job(run_id: str) -> None:
    st = store()
    try:
        run, _ = st.get_run(run_id)
    except NotFound:
        return
    run.status, run.started_at = "running", _now()
    st.save_run(run)
    sheets: list[SheetResult] = []
    sheet_docs: list[str] = []  # the drawing of each sheet, for reviewing the run page by page
    try:
        libs: dict[str, tuple[Library, list]] = {}
        for doc_id in run.doc_ids:
            try:
                d = st.get_drawing(doc_id)
            except NotFound:
                run.warnings.append("A drawing was deleted before it was analysed.")
                continue
            if d.status != "ready":
                run.warnings.append(f"{d.file_name}: {d.error or 'not ready'}; skipped.")
                run.done_steps += len(d.pages)
                continue
            if d.library_id not in libs:
                lib = st.get_library(d.library_id)
                libs[d.library_id] = (lib, _prepared(st, st.templates(lib.id)))
                if not libs[d.library_id][1]:
                    run.warnings.append(f"Library '{lib.name}' has no templates; only its text scan was used.")
            lib, prepared = libs[d.library_id]
            for page in d.pages:
                if run_id in _cancel:
                    run.status = "cancelled"
                    break
                run.current = f"{d.file_name} page {page.n}"
                st.save_run(run)
                res = analyse_one(st, d, page.n, lib, prepared)
                run.warnings += [f"{d.file_name} p{page.n}: {w}" for w in res.warnings]
                sheets.append(SheetResult(d.file_name, res))
                sheet_docs.append(d.id)
                run.done_steps += 1
            st.save_drawing(d)
            if run.status == "cancelled":
                break
        if run.status != "cancelled":
            run.status = "done"
    except Exception as exc:
        run.status, run.error = "error", str(exc)
    run.finished_at, run.current = _now(), ""
    run.tag_count = len(tags_table(sheets, run.columns)[1])
    st.save_run(run, [{"doc_id": doc, "file_name": s.file_name, "result": s.result.model_dump(mode="json")}
                      for doc, s in zip(sheet_docs, sheets)])
    _cancel.discard(run_id)


# -- drawings ---------------------------------------------------------------------

@router.get("/drawings", response_model=list[Drawing])
def list_drawings() -> list[Drawing]:
    return store().drawings()


@router.post("/drawings", response_model=Drawing)
async def upload_drawing(request: Request, filename: str = Query(...), library_id: str = Query(...)) -> Drawing:
    _library(library_id)
    data = await request.body()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "The file is larger than 200 MB.")
    try:
        n = await run_in_threadpool(page_count, data)
    except PdfError as exc:
        raise HTTPException(400, str(exc)) from exc
    if n == 0:
        raise HTTPException(400, "The PDF has no pages.")
    d = Drawing(id=uuid.uuid4().hex, file_name=Path(filename).name, library_id=library_id, uploaded_at=_now())
    store().add_drawing(d, data)
    _worker.submit(identity.carry(_render_job), d.id)
    return d


@router.get("/drawings/{doc_id}", response_model=Drawing)
def get_drawing(doc_id: str) -> Drawing:
    return _drawing(doc_id)


class DrawingEdit(BaseModel):
    library_id: str
    force_ocr: bool = False


@router.put("/drawings/{doc_id}", response_model=Drawing)
def edit_drawing(doc_id: str, body: DrawingEdit) -> Drawing:
    d = _drawing(doc_id)
    _library(body.library_id)
    return store().save_drawing(d.model_copy(update={"library_id": body.library_id, "force_ocr": body.force_ocr}))


@router.delete("/drawings/{doc_id}")
def delete_drawing(doc_id: str) -> dict[str, str]:
    store().delete_drawing(doc_id)
    return {"status": "deleted"}


@router.get("/drawings/{doc_id}/pages/{n}/image.png")
def page_image(doc_id: str, n: int):
    _page(_drawing(doc_id), n)
    return FileResponse(store().page_png(doc_id, n), media_type="image/png", headers={"Cache-Control": "max-age=3600"})


@router.get("/drawings/{doc_id}/pages/{n}/words", response_model=list[Word])
async def words(doc_id: str, n: int) -> list[Word]:
    d = _drawing(doc_id)
    _page(d, n)
    st = store()
    gray = await run_in_threadpool(_gray, st, doc_id, n)
    w, _, _ = await run_in_threadpool(page_words, st, d, n, gray, _library(d.library_id))
    return w


@router.get("/drawings/{doc_id}/pages/{n}/result", response_model=PageResult | None)
def page_result(doc_id: str, n: int) -> PageResult | None:
    _page(_drawing(doc_id), n)
    return store().result(doc_id, n)


@router.post("/drawings/{doc_id}/pages/{n}/analyse", response_model=PageResult)
async def analyse(doc_id: str, n: int) -> PageResult:
    d = _drawing(doc_id)
    _page(d, n)
    st = store()
    res = await run_in_threadpool(analyse_one, st, d, n, _library(d.library_id))
    st.save_drawing(d)
    return res


@router.get("/drawings/{doc_id}/pages/{n}/overrides", response_model=list[PageOverride])
def list_overrides(doc_id: str, n: int) -> list[PageOverride]:
    return list(store().overrides(doc_id, n).values())


@router.put("/drawings/{doc_id}/pages/{n}/overrides/{template_id}", response_model=PageOverride)
def set_override(doc_id: str, n: int, template_id: str, body: PageOverride):
    if body.threshold is not None and not 0.05 <= body.threshold <= 1:
        return _invalid("The threshold must be between 0.05 and 1.", {"threshold": "Between 0.05 and 1."})
    try:
        return store().set_override(doc_id, n, body.model_copy(update={"template_id": template_id}))
    except NotFound as exc:
        raise _nf("drawing or template") from exc


@router.delete("/drawings/{doc_id}/pages/{n}/overrides/{template_id}")
def delete_override(doc_id: str, n: int, template_id: str) -> dict[str, str]:
    store().delete_override(doc_id, n, template_id)
    return {"status": "deleted"}


# -- review: false positives and symbols added by hand -------------------------------

class ReviewAction(BaseModel):
    """reject: mark a detection (symbol or text-scan tag) as a false positive; a symbol
    added by hand is removed instead. restore: undo a rejection. add: place `template_id`
    at the clicked point (x, y), snapped to its best match nearby. tag: type the tag of a
    symbol added by hand. Boxes and points are page-image pixels."""
    action: Literal["reject", "restore", "add", "tag"]
    kind: Literal["symbol", "tag"] = "symbol"
    box: list[float] | None = None
    template_id: str | None = None
    tag: str | None = None
    x: float | None = None
    y: float | None = None
    run_id: str | None = None  # also correct this run's result (tags list, export)


class ReviewResult(BaseModel):
    result: PageResult
    review: PageReview
    symbol: Symbol | None = None  # the symbol just added


@router.get("/drawings/{doc_id}/pages/{n}/review", response_model=PageReview)
def get_review(doc_id: str, n: int) -> PageReview:
    _page(_drawing(doc_id), n)
    return store().review(doc_id, n)


def _box(body: ReviewAction) -> list[float]:
    if not body.box or len(body.box) != 4:
        raise HTTPException(422, "A box [x1, y1, x2, y2] is needed.")
    return body.box


def _change_review(st: SymbolStore, lib: Library, body: ReviewAction, gray, words: list[Word],
                   review: PageReview) -> Symbol | None:
    """Apply one action to the page's review (in place); returns the symbol added, if any."""
    def near(b: list[float], other: list[float]) -> bool:
        return _iou(b, other) >= REVIEW_IOU

    if body.action == "reject":
        b = _box(body)
        if body.kind == "symbol":
            manual = [a for a in review.added if near(b, a.box)]
            if manual:
                review.added = [a for a in review.added if a not in manual]
                return None
        if not any(r.kind == body.kind and near(b, r.box) for r in review.rejected):
            review.rejected.append(Rejection(kind=body.kind, box=b, template_id=body.template_id if body.kind == "symbol" else None,
                                             tag=body.tag if body.kind == "tag" else None))
        return None
    if body.action == "restore":
        b = _box(body)
        review.rejected = [r for r in review.rejected if not (r.kind == body.kind and near(b, r.box))]
        return None
    if body.action == "tag":
        b = _box(body)
        hit = next((a for a in review.added if near(b, a.box)), None)
        if hit is None:
            raise HTTPException(422, "Only a symbol added by hand can have its tag typed.")
        hit.tag_override = (body.tag or "").strip() or None
        return hit
    # add
    if body.template_id is None or body.x is None or body.y is None:
        raise HTTPException(422, "Pick a template and click on the symbol.")
    t = _template(body.template_id)
    if t.library_id != lib.id:
        raise HTTPException(422, f"'{t.desc}' is not in this drawing's library “{lib.name}”.")
    ti = _prepared(st, [t])[0]
    s = locate_near(erase_words(gray, words), ti, body.x, body.y)
    if s is None:
        raise HTTPException(422, f"'{t.desc}' can't be placed there.")
    # Clicking a symbol that was rejected brings it back rather than adding a copy.
    back = [r for r in review.rejected if r.kind == "symbol" and r.template_id in (None, t.id) and near(s.box, r.box)]
    if back:
        review.rejected = [r for r in review.rejected if r not in back]
        return s
    if any(near(s.box, a.box) for a in review.added):
        raise HTTPException(422, "That symbol has already been added.")
    s.tag_override = (body.tag or "").strip() or None
    review.added.append(s)
    return s


@router.post("/drawings/{doc_id}/pages/{n}/review", response_model=ReviewResult)
async def review_page(doc_id: str, n: int, body: ReviewAction):
    """Correct a page's detections. The correction is kept with the drawing page (every
    later analysis re-applies it) and applied at once to the page's latest result and,
    with run_id, to that run's sheet, so its tags list and export change too."""
    d = _drawing(doc_id)
    _page(d, n)
    st = store()
    lib = _library(d.library_id)

    def go():
        run = sheets = None
        index = -1
        if body.run_id:
            run, sheets = _raw_run(body.run_id)
            if run.status in ("queued", "running"):
                raise HTTPException(409, "The run hasn't finished yet.")
            index = _sheet_index(sheets, doc_id, n)
        latest = st.result(doc_id, n)
        if run is None and latest is None:
            raise HTTPException(409, "Analyse the page first.")
        gray = _gray(st, doc_id, n)
        words, source, _ = page_words(st, d, n, gray, lib)
        excluded = apply_exclusion(words, lib.exclusion, gray.shape[1], gray.shape[0])
        review = st.review(doc_id, n).model_copy(deep=True)
        added = _change_review(st, lib, body, gray, excluded, review)
        templates = {t.id: t for t in st.templates(lib.id)}
        region = None
        if source == "ocr":
            provider, _ = ocr_provider()
            region = getattr(provider, "read_region", None)
        st.save_review(doc_id, n, review)

        def fix(res: PageResult) -> PageResult:
            return apply_review(res, words, review, lib, templates, gray, region)

        out = None
        if latest is not None:
            out = fix(latest)
            st.save_result(doc_id, out)
        if run is not None:
            out = fix(PageResult.model_validate(sheets[index]["result"]))
            sheets[index] = {**sheets[index], "result": out.model_dump(mode="json")}
            all_sheets = [SheetResult(sh["file_name"], PageResult.model_validate(sh["result"])) for sh in sheets]
            run.tag_count = len(tags_table(all_sheets, run.columns)[1])
            st.update_run_sheet(run, index, sheets[index])
        if added is not None:
            added = next((x for x in out.symbols if _iou(x.box, added.box) >= REVIEW_IOU), added)
        return ReviewResult(result=out, review=review, symbol=added)

    return await run_in_threadpool(go)


# -- templates ----------------------------------------------------------------------

def _check_template(t: Template) -> dict[str, str]:
    f: dict[str, str] = {}
    if not t.desc.strip():
        f["desc"] = "Give the template a name."
    if not 0.05 <= t.threshold <= 1:
        f["threshold"] = "Between 0.05 and 1."
    if not 1 <= t.buffer_space <= 10:
        f["buffer_space"] = "Between 1 and 10."
    if not t.scales or any(not 0.25 <= s <= 4 for s in t.scales):
        f["scales"] = "Each size must be between 0.25 and 4."
    if t.max_hits < 1:
        f["max_hits"] = "At least 1."
    names = [p.name.strip() for p in t.points]
    if any(not n for n in names):
        f["points"] = "Every tag point needs a name."
    elif len({n.lower() for n in names}) != len(names):
        f["points"] = "Tag point names must be different."
    for p in t.points:
        if not (0 <= p.x <= t.width and 0 <= p.y <= t.height):
            f["points"] = f"Point '{p.name}' is outside the {t.width} x {t.height} template."
        if not 0 <= p.min_overlap <= 1:
            f["points"] = f"Point '{p.name}': minimum overlap must be between 0 and 1."
    err = check_format(t.tag_format, [p.name for p in t.points])
    if err:
        f["tag_format"] = err
    return f


def _new_template(gray, desc: str, library_id: str) -> Template:
    lib = _library(library_id)
    t = Template(id=uuid.uuid4().hex, library_id=library_id, desc=desc.strip() or "Symbol",
                 threshold=lib.default_threshold, width=int(gray.shape[1]), height=int(gray.shape[0]))
    return store().add_template(t, encode_png(gray))


@router.get("/templates", response_model=list[Template])
def list_templates(library_id: str | None = None) -> list[Template]:
    return store().templates(library_id)


class FromPage(BaseModel):
    doc_id: str
    page: int
    rect: list[float] = Field(min_length=4, max_length=4)
    desc: str = "Symbol"
    trim: bool = True


def _cut(st: SymbolStore, d: Drawing, lib: Library, page: int, rect: list[float], trimmed: bool):
    """A template image cut from a page (text erased, optionally trimmed to the ink), where it
    lies on the page, and its view: the same crop with the text left in, and the words inside it
    in template pixels (shown in the template editor, so tag points can be put on the text)."""
    gray = _gray(st, d.id, page)
    w, _, _ = page_words(st, d, page, gray, lib)
    clean = erase_words(gray, w)
    if trimmed:
        box = trim_box(clean, rect)
    else:
        crop(clean, rect)  # validates the size
        box = [min(rect[0], rect[2]), min(rect[1], rect[3]), max(rect[0], rect[2]), max(rect[1], rect[3])]
    img = crop(clean, box)
    x0, y0 = max(round(min(box[0], box[2])), 0), max(round(min(box[1], box[3])), 0)  # where crop() starts
    return img, box, crop(gray, box), _words_in(w, x0, y0, img.shape[1], img.shape[0])


def _words_in(words: list[Word], x0: int, y0: int, width: int, height: int) -> list[Word]:
    """The words that overlap the crop at (x0, y0) of width x height, in its pixels, clipped to it."""
    out = []
    for wd in words:
        x1, y1, x2, y2 = wd.box[0] - x0, wd.box[1] - y0, wd.box[2] - x0, wd.box[3] - y0
        if x2 <= 0 or y2 <= 0 or x1 >= width or y1 >= height:
            continue
        out.append(wd.model_copy(update={"box": [max(x1, 0), max(y1, 0), min(x2, width), min(y2, height)]}))
    return out


@router.post("/templates/from-page", response_model=Template)
async def template_from_page(body: FromPage) -> Template:
    """Cut a template from a page render (lossless, with the page text erased) into the
    drawing's library."""
    d = _drawing(body.doc_id)
    _page(d, body.page)
    st = store()
    lib = _library(d.library_id)
    try:
        img, _, view, words = await run_in_threadpool(_cut, st, d, lib, body.page, body.rect, body.trim)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    t = _new_template(img, body.desc, d.library_id)
    st.set_template_view(t.id, encode_png(view), words)
    return t


class TemplatePreview(BaseModel):
    rect: list[float]  # what the template would keep, in page pixels
    width: int
    height: int
    png: str  # base64: the template (text erased, as it is matched)
    view_png: str = ""  # base64: the same with the page text left in
    words: list[Word] = Field(default_factory=list)  # the text inside it, in template pixels


@router.post("/templates/preview", response_model=TemplatePreview)
async def template_preview(body: FromPage) -> TemplatePreview:
    """What New template would cut from this box, without saving anything."""
    d = _drawing(body.doc_id)
    _page(d, body.page)
    st = store()
    try:
        img, box, view, words = await run_in_threadpool(_cut, st, d, _library(d.library_id), body.page, body.rect, body.trim)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return TemplatePreview(rect=box, width=int(img.shape[1]), height=int(img.shape[0]),
                           png=base64.b64encode(encode_png(img)).decode(),
                           view_png=base64.b64encode(encode_png(view)).decode(), words=words)


def _decode_upload(data: bytes):
    import cv2
    import numpy as np
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise HTTPException(400, "That file is not a PNG, JPEG, BMP or TIFF image.")
    if img.ndim == 3 and img.shape[2] == 4:  # transparent -> white
        alpha = img[:, :, 3:4].astype("float32") / 255
        img = (img[:, :, :3] * alpha + 255 * (1 - alpha)).astype("uint8")
    if img.ndim == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return img


@router.post("/templates/upload", response_model=Template)
async def template_upload(request: Request, filename: str = Query(...), library_id: str = Query(...)) -> Template:
    """A symbol image file as a new template (cut it at the drawings' 200 DPI scale)."""
    return _new_template(_decode_upload(await request.body()), Path(filename).stem, library_id)


@router.get("/templates/{template_id}", response_model=Template)
def get_template(template_id: str) -> Template:
    return _template(template_id)


@router.put("/templates/{template_id}", response_model=Template)
def save_template(template_id: str, body: Template):
    old = _template(template_id)
    _library(body.library_id)
    body = body.model_copy(update={"id": template_id, "width": old.width, "height": old.height})
    fields = _check_template(body)
    if body.mask_mode == "custom" and not old.has_custom_mask:
        fields["mask_mode"] = "Paint or upload a mask first."
    if fields:
        return _invalid("Fix the highlighted fields.", fields)
    return store().save_template(body)


@router.delete("/templates/{template_id}")
def delete_template(template_id: str) -> dict[str, str]:
    try:
        store().delete_template(template_id)
    except NotFound:
        pass
    return {"status": "deleted"}


class Move(BaseModel):
    index: int


@router.post("/templates/{template_id}/move", response_model=Template)
def move_template(template_id: str, body: Move) -> Template:
    _template(template_id)
    return store().move_template(template_id, body.index)


@router.get("/templates/{template_id}/image.png")
def template_image(template_id: str):
    try:
        return Response(store().template_image(template_id), media_type="image/png")
    except NotFound as exc:
        raise _nf("template") from exc


@router.get("/templates/{template_id}/view.png")
def template_view_image(template_id: str):
    """The template with its page text, for the editor; the template itself when it has no view."""
    try:
        view = store().template_view(template_id)
        return Response(view[0] if view else store().template_image(template_id), media_type="image/png")
    except NotFound as exc:
        raise _nf("template") from exc


@router.get("/templates/{template_id}/words", response_model=list[Word])
def template_words(template_id: str) -> list[Word]:
    """The text on the template as it was cut from its page, in template pixels ([] if none is kept)."""
    try:
        view = store().template_view(template_id)
    except NotFound as exc:
        raise _nf("template") from exc
    return view[1] if view else []


def _mask_png(mask) -> bytes:
    import numpy as np
    return encode_png(np.where(mask > 0, 255, 0).astype("uint8"))


@router.get("/templates/{template_id}/mask.png")
def template_mask(template_id: str, mode: Literal["auto", "custom", "none"] | None = None,
                  buffer_space: int | None = None):
    """The mask a template is matched with (white = scored), for `mode` (default: its own)."""
    import numpy as np
    t = _template(template_id)
    st = store()
    gray = decode_gray(st.template_image(template_id))
    mode = mode or t.mask_mode
    custom = decode_gray(st.template_mask(template_id)) if mode == "custom" and t.has_custom_mask else None
    if mode == "custom" and custom is None:
        mode = "auto"
    mask = effective_mask(mode, gray, buffer_space or t.buffer_space, custom)
    if mask is None:
        mask = np.full(gray.shape, 255, np.uint8)
    return Response(_mask_png(mask), media_type="image/png")


@router.put("/templates/{template_id}/mask", response_model=Template)
async def set_template_mask(template_id: str, request: Request) -> Template:
    """Store a custom mask (an image the template's size; white or opaque = scored) and use it."""
    from workbench_core.symbols.templates import custom_mask
    t = _template(template_id)
    img = _decode_upload(await request.body())
    m = custom_mask(img, (t.height, t.width))
    if not m.any():
        raise HTTPException(400, "The mask is empty: paint the parts of the symbol that should be compared.")
    return store().set_template_mask(template_id, _mask_png(m))


@router.delete("/templates/{template_id}/mask", response_model=Template)
def clear_template_mask(template_id: str) -> Template:
    _template(template_id)
    return store().set_template_mask(template_id, None)


class TrialRequest(BaseModel):
    doc_id: str
    page: int
    template: Template | None = None  # unsaved edits
    mask_png: str | None = None  # unsaved custom mask (base64 PNG)


class TrialResult(BaseModel):
    symbols: list[Symbol]
    best: float
    skipped: str | None = None


@router.post("/templates/{template_id}/test", response_model=TrialResult)
async def test_template(template_id: str, body: TrialRequest) -> TrialResult:
    """Match one template on one page (no other templates, nothing saved) to tune it."""
    old = _template(template_id)
    t = (body.template or old).model_copy(update={"id": template_id, "width": old.width, "height": old.height,
                                                  "active": True})
    d = _drawing(body.doc_id)
    _page(d, body.page)
    st = store()
    lib = _library(d.library_id)

    def go() -> TrialResult:
        gray = _gray(st, d.id, body.page)
        w, _, _ = page_words(st, d, body.page, gray, lib)
        custom = None
        if t.mask_mode == "custom":
            custom = decode_gray(base64.b64decode(body.mask_png)) if body.mask_png else _custom_mask(st, t)
            if custom is None:
                t.mask_mode = "auto"
        ti = prepare(t, decode_gray(st.template_image(template_id)), custom)
        ov = {k: v for k, v in st.overrides(d.id, body.page).items() if k == template_id and not v.ignore}
        out = locate_symbols(erase_words(gray, w), [ti], ov)
        for s in out.symbols:
            s.parts = resolve_points(s, t, w)
            s.tag = format_tag(t, s.parts)
        return TrialResult(symbols=out.symbols, best=out.best.get(template_id, 0.0),
                           skipped=out.skipped[0].reason if out.skipped else None)
    return await run_in_threadpool(go)


class OcrStatus(BaseModel):
    available: bool
    engine: str | None
    reason: str | None


@router.get("/ocr", response_model=OcrStatus)
def ocr_status() -> OcrStatus:
    p, why = ocr_provider()
    return OcrStatus(available=p is not None, engine=getattr(p, "name", None), reason=why)


# -- runs ---------------------------------------------------------------------------------

class NewRun(BaseModel):
    doc_ids: list[str] = Field(min_length=1)


@router.post("/runs", response_model=RunInfo)
def start_run(body: NewRun) -> RunInfo:
    st = store()
    total, columns = 0, []
    for doc_id in body.doc_ids:
        d = _drawing(doc_id)
        total += max(len(d.pages), 1)
        try:
            columns += [c for c in group_names(_library(d.library_id)) if c not in columns]
        except ValueError:
            pass
    run = RunInfo(id=uuid.uuid4().hex, doc_ids=body.doc_ids, total_steps=total, columns=columns)
    st.save_run(run)
    _worker.submit(identity.carry(_run_job), run.id)
    return run


@router.get("/runs", response_model=list[RunInfo])
def list_runs() -> list[RunInfo]:
    return store().runs()


def _raw_run(run_id: str) -> tuple[RunInfo, list[dict]]:
    """The run and its stored sheets, each with its drawing id (runs saved before reviews
    existed only kept the file name: match it against the run's drawings)."""
    st = store()
    try:
        run, sheets = st.get_run(run_id)
    except NotFound as exc:
        raise _nf("run") from exc
    if any("doc_id" not in sh for sh in sheets):
        by_name: dict[str, str] = {}
        for doc_id in run.doc_ids:
            try:
                by_name.setdefault(st.get_drawing(doc_id).file_name, doc_id)
            except NotFound:
                pass
        for sh in sheets:
            sh.setdefault("doc_id", by_name.get(sh["file_name"]))
    return run, sheets


def _run(run_id: str) -> tuple[RunInfo, list[SheetResult]]:
    run, sheets = _raw_run(run_id)
    return run, [SheetResult(s["file_name"], PageResult.model_validate(s["result"])) for s in sheets]


@router.get("/runs/{run_id}", response_model=RunInfo)
def get_run(run_id: str) -> RunInfo:
    return _run(run_id)[0]


@router.post("/runs/{run_id}/cancel", response_model=RunInfo)
def cancel_run(run_id: str) -> RunInfo:
    run, _ = _run(run_id)
    if run.status in ("queued", "running"):
        _cancel.add(run_id)
    return run


@router.delete("/runs/{run_id}")
def delete_run(run_id: str) -> dict[str, str]:
    store().delete_run(run_id)
    return {"status": "deleted"}


class TagsTable(BaseModel):
    headers: list[str]
    rows: list[dict[str, str]]


def run_tags(run_id: str) -> tuple[RunInfo, list[SheetResult], TagsTable]:
    run, sheets = _run(run_id)
    if run.status in ("queued", "running"):
        raise HTTPException(409, "The run hasn't finished yet.")
    headers, rows = tags_table(sheets, run.columns)
    return run, sheets, TagsTable(headers=headers, rows=rows)


@router.get("/runs/{run_id}/tags", response_model=TagsTable)
def get_run_tags(run_id: str) -> TagsTable:
    return run_tags(run_id)[2]


class RunSheet(BaseModel):
    doc_id: str | None
    file_name: str
    page: int
    symbols: int
    tags: int
    rejected: int
    added: int


@router.get("/runs/{run_id}/sheets", response_model=list[RunSheet])
def get_run_sheets(run_id: str) -> list[RunSheet]:
    """The pages a run analysed, for reviewing its detections on the drawings."""
    _, sheets = _raw_run(run_id)
    out = []
    for sh in sheets:
        r = PageResult.model_validate(sh["result"])
        out.append(RunSheet(doc_id=sh["doc_id"], file_name=sh["file_name"], page=r.page, symbols=len(r.symbols),
                            tags=len(r.tags), rejected=len(r.rejected_symbols) + len(r.rejected_tags),
                            added=sum(1 for x in r.symbols if x.origin == "manual")))
    return out


def _sheet_index(sheets: list[dict], doc_id: str, n: int) -> int:
    for i, sh in enumerate(sheets):
        if sh["doc_id"] == doc_id and sh["result"]["page"] == n:
            return i
    raise _nf("page in this run")


@router.get("/runs/{run_id}/sheets/{doc_id}/{n}", response_model=PageResult)
def get_run_sheet(run_id: str, doc_id: str, n: int) -> PageResult:
    _, sheets = _raw_run(run_id)
    return PageResult.model_validate(sheets[_sheet_index(sheets, doc_id, n)]["result"])


class ExportRequest(BaseModel):
    format: Literal["csv", "xlsx"] = "xlsx"
    path: str | None = None


MEDIA = {"csv": "text/csv", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}


@router.post("/runs/{run_id}/export")
def export_run(run_id: str, body: ExportRequest, request: Request):
    _json_only(request)
    run, sheets, _ = run_tags(run_id)
    title = f"Tags from {len({s.file_name for s in sheets})} drawing(s), run {run.finished_at:%Y-%m-%d %H:%M}"
    data = tags_csv(sheets, run.columns) if body.format == "csv" else tags_xlsx(sheets, title, run.columns)
    if body.path is None:
        return Response(data, media_type=MEDIA[body.format],
                        headers={"Content-Disposition": f'attachment; filename="tags.{body.format}"'})
    return _write(body.path, data, f".{body.format}")
