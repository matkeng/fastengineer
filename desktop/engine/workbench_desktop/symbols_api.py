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
    Exclusion,
    Library,
    PageInfo,
    PageOverride,
    PageResult,
    RunInfo,
    SheetResult,
    Symbol,
    Template,
    Word,
    analyse_page,
    choose_words,
    tags_table,
)
from workbench_core.symbols import ocr as ocr_mod
from workbench_core.symbols.export import tags_csv, tags_xlsx
from workbench_core.symbols.match import locate_symbols, prepare
from workbench_core.symbols.render import PdfError, decode_gray, encode_png, page_count, render_pages
from workbench_core.symbols.tags import check_format, compile_pattern, format_tag, group_names, resolve_points
from workbench_core.symbols.templates import crop, effective_mask, erase_words, trim

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
        for k in ("id", "width", "height", "priority", "library_id", "has_custom_mask"):
            t.pop(k, None)
        tpl = Template(id=uuid.uuid4().hex, library_id=lib.id, width=int(gray.shape[1]), height=int(gray.shape[0]), **t)
        out.append(st.add_template(tpl, encode_png(gray), mask))
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
    res = analyse_page(n, gray, words, source, prepared, st.overrides(d.id, n), lib)
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
    st.save_run(run, [{"file_name": s.file_name, "result": s.result.model_dump(mode="json")} for s in sheets])
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
    _worker.submit(_render_job, d.id)
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


@router.post("/templates/from-page", response_model=Template)
async def template_from_page(body: FromPage) -> Template:
    """Cut a template from a page render (lossless, with the page text erased) into the
    drawing's library."""
    d = _drawing(body.doc_id)
    _page(d, body.page)
    st = store()
    lib = _library(d.library_id)

    def cut():
        gray = _gray(st, d.id, body.page)
        w, _, _ = page_words(st, d, body.page, gray, lib)
        img = crop(erase_words(gray, w), body.rect)
        return trim(img) if body.trim else img
    try:
        img = await run_in_threadpool(cut)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _new_template(img, body.desc, d.library_id)


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
    _worker.submit(_run_job, run.id)
    return run


@router.get("/runs", response_model=list[RunInfo])
def list_runs() -> list[RunInfo]:
    return store().runs()


def _run(run_id: str) -> tuple[RunInfo, list[SheetResult]]:
    try:
        run, sheets = store().get_run(run_id)
    except NotFound as exc:
        raise _nf("run") from exc
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
