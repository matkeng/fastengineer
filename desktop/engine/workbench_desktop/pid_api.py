"""P&ID analysis endpoints over workbench_core.pid.

Rendering and analysis runs go through one background worker thread, so the UI
stays responsive and jobs never compete for CPU; the UI polls their status."""

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

from workbench_core.pid import (
    Drawing,
    Exclusion,
    PageInfo,
    PageOverride,
    PageResult,
    RunInfo,
    Settings,
    SheetResult,
    Symbol,
    Template,
    Word,
    analyse_page,
    choose_words,
    tags_table,
)
from workbench_core.pid import ocr as ocr_mod
from workbench_core.pid.export import tags_csv, tags_xlsx
from workbench_core.pid.match import locate_symbols, prepare
from workbench_core.pid.render import PdfError, decode_gray, encode_png, page_count, render_pages
from workbench_core.pid.tags import compile_pattern, format_tag, resolve_points
from workbench_core.pid.templates import crop, erase_words, make_mask, trim

from .storage import NotFound, PidStore, get_pid

router = APIRouter(prefix="/api/pid", tags=["P&ID analysis"])

MAX_UPLOAD = 200 * 1024 * 1024
_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pid")
_cancel: set[str] = set()
_lock = threading.Lock()
ocr_provider = ocr_mod.default_provider  # tests replace this


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _nf(what: str) -> HTTPException:
    return HTTPException(404, f"That {what} no longer exists.")


def _invalid(message: str, fields: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": message, "fields": fields or {}})


def _drawing(doc_id: str) -> Drawing:
    try:
        return get_pid().get_drawing(doc_id)
    except NotFound as exc:
        raise _nf("drawing") from exc


def _template(template_id: str) -> Template:
    try:
        return get_pid().get_template(template_id)
    except NotFound as exc:
        raise _nf("template") from exc


def _page(d: Drawing, n: int) -> PageInfo:
    if d.status != "ready":
        raise HTTPException(409, "The drawing is still being prepared." if d.status == "rendering" else (d.error or "The drawing could not be read."))
    if not 1 <= n <= len(d.pages):
        raise HTTPException(404, f"The drawing has {len(d.pages)} page(s).")
    return d.pages[n - 1]


def _lib_key(drawing_type: str, block_set: str) -> str:
    return f"{drawing_type}/{block_set}"


# -- words ----------------------------------------------------------------------

def _load_words(path: Path) -> list[Word]:
    return [Word(**w) for w in json.loads(path.read_text())] if path.exists() else []


def page_words(pid: PidStore, d: Drawing, n: int, gray, settings: Settings) -> tuple[list[Word], str, list[str]]:
    """The words a page is analysed with: its text layer, or OCR (cached per page)."""
    pdf_words = _load_words(pid.words_file(d.id, n))
    cached = pid.words_file(d.id, n, "ocr")
    if (d.force_ocr or len(pdf_words) < settings.min_pdf_words) and cached.exists():
        return _load_words(cached), "ocr", []
    words, source, warnings = choose_words(gray, pdf_words, settings, d.force_ocr, ocr_provider)
    if source == "ocr":
        cached.write_text(json.dumps([w.model_dump() for w in words]))
    return words, source, warnings


def _gray(pid: PidStore, doc_id: str, n: int):
    return decode_gray(pid.page_png(doc_id, n).read_bytes())


def _prepared(pid: PidStore, templates: list[Template]):
    return [prepare(t, decode_gray(pid.template_image(t.id))) for t in templates]


# -- background jobs ---------------------------------------------------------------

def _render_job(doc_id: str) -> None:
    pid = get_pid()
    try:
        d = pid.get_drawing(doc_id)
    except NotFound:
        return
    try:
        pages = []
        for p in render_pages((pid.doc_dir(doc_id) / "source.pdf").read_bytes()):
            pid.page_png(doc_id, p.n).write_bytes(p.png)
            pid.words_file(doc_id, p.n).write_text(json.dumps([w.model_dump() for w in p.words]))
            pages.append(PageInfo(n=p.n, width_px=p.width_px, height_px=p.height_px, rotation=p.rotation,
                                  text_source="pdf" if p.words else "none", word_count=len(p.words)))
        d = d.model_copy(update={"pages": pages, "status": "ready", "error": None})
    except Exception as exc:  # report it on the drawing rather than losing it in a thread
        d = d.model_copy(update={"status": "error", "error": str(exc)})
    try:
        pid.save_drawing(d)
    except NotFound:
        pass  # deleted while rendering


def analyse_one(pid: PidStore, d: Drawing, n: int, settings: Settings, prepared=None) -> PageResult:
    gray = _gray(pid, d.id, n)
    words, source, warnings = page_words(pid, d, n, gray, settings)
    if prepared is None:
        prepared = _prepared(pid, pid.templates(d.drawing_type, d.block_set))
    res = analyse_page(n, gray, words, source, prepared, pid.overrides(d.id, n), settings,
                       settings.exclusions.get(_lib_key(d.drawing_type, d.block_set)))
    res.warnings = warnings + res.warnings
    pid.save_result(d.id, res)
    page = d.pages[n - 1]
    page.text_source, page.word_count = source, len(words)
    page.warnings = warnings
    return res


def _run_job(run_id: str) -> None:
    pid = get_pid()
    try:
        run, _ = pid.get_run(run_id)
    except NotFound:
        return
    run.status, run.started_at = "running", _now()
    pid.save_run(run)
    sheets: list[SheetResult] = []
    try:
        settings = pid.settings()
        libs: dict[str, list] = {}
        for doc_id in run.doc_ids:
            try:
                d = pid.get_drawing(doc_id)
            except NotFound:
                run.warnings.append("A drawing was deleted before it was analysed.")
                continue
            if d.status != "ready":
                run.warnings.append(f"{d.file_name}: {d.error or 'not ready'}; skipped.")
                run.done_steps += len(d.pages)
                continue
            key = _lib_key(d.drawing_type, d.block_set)
            if key not in libs:
                libs[key] = _prepared(pid, pid.templates(d.drawing_type, d.block_set))
                if not libs[key]:
                    run.warnings.append(f"No templates for {key}; {d.file_name} uses the tag-pattern scan only.")
            for page in d.pages:
                if run_id in _cancel:
                    run.status = "cancelled"
                    break
                run.current = f"{d.file_name} page {page.n}"
                pid.save_run(run)
                res = analyse_one(pid, d, page.n, settings, libs[key])
                run.warnings += [f"{d.file_name} p{page.n}: {w}" for w in res.warnings]
                sheets.append(SheetResult(d.file_name, res))
                run.done_steps += 1
            pid.save_drawing(d)
            if run.status == "cancelled":
                break
        if run.status != "cancelled":
            run.status = "done"
    except Exception as exc:
        run.status, run.error = "error", str(exc)
    run.finished_at, run.current = _now(), ""
    run.tag_count = len(tags_table(sheets)[1])
    pid.save_run(run, [{"file_name": s.file_name, "result": s.result.model_dump(mode="json")} for s in sheets])
    _cancel.discard(run_id)


# -- drawings ---------------------------------------------------------------------

@router.get("/drawings", response_model=list[Drawing])
def list_drawings() -> list[Drawing]:
    return get_pid().drawings()


@router.post("/drawings", response_model=Drawing)
async def upload_drawing(request: Request, filename: str = Query(...), drawing_type: str = "PID",
                         block_set: str = "FIR") -> Drawing:
    data = await request.body()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "The file is larger than 200 MB.")
    try:
        n = await run_in_threadpool(page_count, data)
    except PdfError as exc:
        raise HTTPException(400, str(exc)) from exc
    if n == 0:
        raise HTTPException(400, "The PDF has no pages.")
    d = Drawing(id=uuid.uuid4().hex, file_name=Path(filename).name, drawing_type=drawing_type.strip() or "PID",
                block_set=block_set.strip() or "FIR", uploaded_at=_now())
    get_pid().add_drawing(d, data)
    _worker.submit(_render_job, d.id)
    return d


@router.get("/drawings/{doc_id}", response_model=Drawing)
def get_drawing(doc_id: str) -> Drawing:
    return _drawing(doc_id)


class DrawingEdit(BaseModel):
    drawing_type: str
    block_set: str
    force_ocr: bool = False


@router.put("/drawings/{doc_id}", response_model=Drawing)
def edit_drawing(doc_id: str, body: DrawingEdit) -> Drawing:
    d = _drawing(doc_id)
    d = d.model_copy(update={"drawing_type": body.drawing_type.strip() or "PID",
                             "block_set": body.block_set.strip() or "FIR", "force_ocr": body.force_ocr})
    return get_pid().save_drawing(d)


@router.delete("/drawings/{doc_id}")
def delete_drawing(doc_id: str) -> dict[str, str]:
    get_pid().delete_drawing(doc_id)
    return {"status": "deleted"}


@router.get("/drawings/{doc_id}/pages/{n}/image.png")
def page_image(doc_id: str, n: int):
    _page(_drawing(doc_id), n)
    return FileResponse(get_pid().page_png(doc_id, n), media_type="image/png",
                        headers={"Cache-Control": "max-age=3600"})


@router.get("/drawings/{doc_id}/pages/{n}/words", response_model=list[Word])
async def words(doc_id: str, n: int) -> list[Word]:
    d = _drawing(doc_id)
    _page(d, n)
    pid = get_pid()
    gray = await run_in_threadpool(_gray, pid, doc_id, n)
    w, _, _ = await run_in_threadpool(page_words, pid, d, n, gray, pid.settings())
    return w


@router.get("/drawings/{doc_id}/pages/{n}/result", response_model=PageResult | None)
def page_result(doc_id: str, n: int) -> PageResult | None:
    _page(_drawing(doc_id), n)
    return get_pid().result(doc_id, n)


@router.post("/drawings/{doc_id}/pages/{n}/analyse", response_model=PageResult)
async def analyse(doc_id: str, n: int) -> PageResult:
    d = _drawing(doc_id)
    _page(d, n)
    pid = get_pid()
    res = await run_in_threadpool(analyse_one, pid, d, n, pid.settings())
    pid.save_drawing(d)
    return res


@router.get("/drawings/{doc_id}/pages/{n}/overrides", response_model=list[PageOverride])
def list_overrides(doc_id: str, n: int) -> list[PageOverride]:
    return list(get_pid().overrides(doc_id, n).values())


@router.put("/drawings/{doc_id}/pages/{n}/overrides/{template_id}", response_model=PageOverride)
def set_override(doc_id: str, n: int, template_id: str, body: PageOverride):
    if body.threshold is not None and not 0.05 <= body.threshold <= 1:
        return _invalid("The threshold must be between 0.05 and 1.", {"threshold": "Between 0.05 and 1."})
    try:
        return get_pid().set_override(doc_id, n, body.model_copy(update={"template_id": template_id}))
    except NotFound as exc:
        raise _nf("drawing or template") from exc


@router.delete("/drawings/{doc_id}/pages/{n}/overrides/{template_id}")
def delete_override(doc_id: str, n: int, template_id: str) -> dict[str, str]:
    get_pid().delete_override(doc_id, n, template_id)
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
        f["scales"] = "Each scale must be between 0.25 and 4."
    if t.max_hits < 1:
        f["max_hits"] = "At least 1."
    names = [p.name.strip() for p in t.points]
    if any(not n for n in names):
        f["points"] = "Every tag point needs a name."
    elif len(set(n.lower() for n in names)) != len(names):
        f["points"] = "Tag point names must be different."
    for p in t.points:
        if not (0 <= p.x <= t.width and 0 <= p.y <= t.height):
            f["points"] = f"Point '{p.name}' is outside the {t.width} x {t.height} template."
        if not 0 <= p.min_overlap <= 1:
            f["points"] = f"Point '{p.name}': minimum overlap must be between 0 and 1."
    if t.tag_format.strip():
        try:
            t.tag_format.format_map({p.name: "X" for p in t.points})
        except KeyError as exc:
            f["tag_format"] = f"{{{exc.args[0]}}} is not one of the tag point names."
        except (ValueError, IndexError):
            f["tag_format"] = "Use {PointName} placeholders, e.g. {Function}-{Number}."
    return f


def _new_template(gray, desc: str, drawing_type: str, block_set: str, **extra) -> Template:
    pid = get_pid()
    t = Template(id=uuid.uuid4().hex, desc=desc.strip() or "Symbol", drawing_type=drawing_type.strip() or "PID",
                 block_set=block_set.strip() or "FIR", width=int(gray.shape[1]), height=int(gray.shape[0]), **extra)
    fields = _check_template(t)
    if fields:
        raise HTTPException(422, next(iter(fields.values())))
    return pid.add_template(t, encode_png(gray), extra.get("priority"))


class Library(BaseModel):
    drawing_type: str
    block_set: str
    templates: int
    drawings: int


@router.get("/libraries", response_model=list[Library])
def libraries() -> list[Library]:
    pid = get_pid()
    counts: dict[tuple[str, str], list[int]] = {}
    for t in pid.templates():
        counts.setdefault((t.drawing_type, t.block_set), [0, 0])[0] += 1
    for d in pid.drawings():
        counts.setdefault((d.drawing_type, d.block_set), [0, 0])[1] += 1
    return [Library(drawing_type=k[0], block_set=k[1], templates=v[0], drawings=v[1]) for k, v in sorted(counts.items())]


@router.get("/templates", response_model=list[Template])
def list_templates(drawing_type: str | None = None, block_set: str | None = None) -> list[Template]:
    return get_pid().templates(drawing_type, block_set)


class FromPage(BaseModel):
    doc_id: str
    page: int
    rect: list[float] = Field(min_length=4, max_length=4)
    desc: str = "Symbol"
    trim: bool = True


@router.post("/templates/from-page", response_model=Template)
async def template_from_page(body: FromPage) -> Template:
    """Cut a template from a page render (lossless, with the page text erased)."""
    d = _drawing(body.doc_id)
    _page(d, body.page)
    pid = get_pid()

    def cut():
        gray = _gray(pid, d.id, body.page)
        w, _, _ = page_words(pid, d, body.page, gray, pid.settings())
        img = crop(erase_words(gray, w), body.rect)
        return trim(img) if body.trim else img
    try:
        img = await run_in_threadpool(cut)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _new_template(img, body.desc, d.drawing_type, d.block_set)


@router.post("/templates/upload", response_model=Template)
async def template_upload(request: Request, filename: str = Query(...), drawing_type: str = "PID",
                          block_set: str = "FIR") -> Template:
    import cv2
    import numpy as np
    data = await request.body()
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise HTTPException(400, "That file is not a PNG, JPEG, BMP or TIFF image.")
    return _new_template(img, Path(filename).stem, drawing_type, block_set)


class LibraryFile(BaseModel):
    templates: list[dict]
    exclusions: dict[str, Exclusion] = Field(default_factory=dict)


@router.post("/templates/import", response_model=list[Template])
def import_templates(body: LibraryFile) -> list[Template]:
    """Load a template library file (as written by export, or samples/pid-templates.json)."""
    out = []
    for raw in body.templates:
        raw = dict(raw)
        try:
            gray = decode_gray(base64.b64decode(raw.pop("image_png")))
        except Exception as exc:
            raise HTTPException(400, f"Template '{raw.get('desc', '?')}' has no readable image.") from exc
        for k in ("id", "width", "height", "priority"):
            raw.pop(k, None)
        out.append(_new_template(gray, raw.pop("desc", "Symbol"), raw.pop("drawing_type", "PID"),
                                 raw.pop("block_set", "FIR"), **raw))
    if body.exclusions:
        pid = get_pid()
        s = pid.settings()
        s.exclusions.update(body.exclusions)
        pid.save_settings(s)
    return out


class LibraryExport(BaseModel):
    drawing_type: str
    block_set: str
    path: str | None = None  # desktop: chosen in a Save As dialog


@router.post("/templates/export")
def export_templates(body: LibraryExport, request: Request):
    if not request.headers.get("content-type", "").startswith("application/json"):
        raise HTTPException(415, "Expected application/json")
    lib = _library_file(body.drawing_type, body.block_set)
    if body.path is None:
        return lib
    target = Path(body.path)
    if target.suffix.lower() != ".json":
        target = target.with_suffix(".json")
    try:
        target.write_text(json.dumps(lib, indent=1))
    except OSError as exc:
        raise HTTPException(409, f"Could not save {target.name}: {exc.strerror or exc}.") from exc
    return {"path": str(target)}


def _library_file(drawing_type: str, block_set: str) -> dict:
    pid = get_pid()
    ts = []
    for t in pid.templates(drawing_type, block_set):
        d = t.model_dump(exclude={"id", "width", "height"})
        d["image_png"] = base64.b64encode(pid.template_image(t.id)).decode()
        ts.append(d)
    ex = pid.settings().exclusions.get(_lib_key(drawing_type, block_set))
    return {"format": "drawing-workbench-pid-templates", "version": 1, "templates": ts,
            "exclusions": {_lib_key(drawing_type, block_set): ex.model_dump()} if ex else {}}


@router.get("/templates/{template_id}", response_model=Template)
def get_template(template_id: str) -> Template:
    return _template(template_id)


@router.put("/templates/{template_id}", response_model=Template)
def save_template(template_id: str, body: Template):
    old = _template(template_id)
    body = body.model_copy(update={"id": template_id, "width": old.width, "height": old.height})
    fields = _check_template(body)
    if fields:
        return _invalid("Fix the highlighted fields.", fields)
    return get_pid().save_template(body)


@router.delete("/templates/{template_id}")
def delete_template(template_id: str) -> dict[str, str]:
    try:
        get_pid().delete_template(template_id)
    except NotFound:
        pass
    return {"status": "deleted"}


class Move(BaseModel):
    index: int


@router.post("/templates/{template_id}/move", response_model=Template)
def move_template(template_id: str, body: Move) -> Template:
    _template(template_id)
    return get_pid().move_template(template_id, body.index)


@router.get("/templates/{template_id}/image.png")
def template_image(template_id: str):
    try:
        return Response(get_pid().template_image(template_id), media_type="image/png")
    except NotFound as exc:
        raise _nf("template") from exc


@router.get("/templates/{template_id}/mask.png")
def template_mask(template_id: str, buffer_space: int | None = None):
    t = _template(template_id)
    gray = decode_gray(get_pid().template_image(template_id))
    import numpy as np
    mask = make_mask(gray, buffer_space or t.buffer_space)
    return Response(encode_png(np.where(mask > 0, 0, 255).astype("uint8")), media_type="image/png")


class TestRequest(BaseModel):
    doc_id: str
    page: int
    template: Template | None = None  # unsaved edits


class TestResult(BaseModel):
    symbols: list[Symbol]
    best: float
    skipped: str | None = None


@router.post("/templates/{template_id}/test", response_model=TestResult)
async def test_template(template_id: str, body: TestRequest) -> TestResult:
    """Match one template on one page (no other templates, nothing saved) to tune it."""
    t = body.template or _template(template_id)
    old = _template(template_id)
    t = t.model_copy(update={"id": template_id, "width": old.width, "height": old.height, "active": True})
    d = _drawing(body.doc_id)
    _page(d, body.page)
    pid = get_pid()

    def go() -> TestResult:
        gray = _gray(pid, d.id, body.page)
        w, _, _ = page_words(pid, d, body.page, gray, pid.settings())
        ti = prepare(t, decode_gray(pid.template_image(template_id)))
        ov = {k: v for k, v in pid.overrides(d.id, body.page).items() if k == template_id and not v.ignore}
        out = locate_symbols(erase_words(gray, w), [ti], ov)
        for s in out.symbols:
            s.parts = resolve_points(s, t, w)
            s.tag = format_tag(t, s.parts)
        return TestResult(symbols=out.symbols, best=out.best.get(template_id, 0.0),
                          skipped=out.skipped[0].reason if out.skipped else None)
    return await run_in_threadpool(go)


# -- settings --------------------------------------------------------------------------

@router.get("/settings", response_model=Settings)
def get_settings() -> Settings:
    return get_pid().settings()


@router.put("/settings", response_model=Settings)
def save_settings(body: Settings):
    try:
        compile_pattern(body.tag_pattern)
    except ValueError as exc:
        return _invalid(str(exc), {"tag_pattern": str(exc)})
    if body.min_pdf_words < 0:
        return _invalid("Must be 0 or more.", {"min_pdf_words": "Must be 0 or more."})
    for key, ex in body.exclusions.items():
        for a in ex.areas:
            if len(a) != 4 or not all(0 <= v <= 1 for v in a):
                return _invalid(f"{key}: exclusion areas are page fractions between 0 and 1.", {"exclusions": key})
    return get_pid().save_settings(body)


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
    pid = get_pid()
    total = 0
    for doc_id in body.doc_ids:
        d = _drawing(doc_id)
        total += max(len(d.pages), 1)
    run = RunInfo(id=uuid.uuid4().hex, doc_ids=body.doc_ids, total_steps=total)
    pid.save_run(run)
    _worker.submit(_run_job, run.id)
    return run


@router.get("/runs", response_model=list[RunInfo])
def list_runs() -> list[RunInfo]:
    return get_pid().runs()


def _run(run_id: str) -> tuple[RunInfo, list[SheetResult]]:
    try:
        run, sheets = get_pid().get_run(run_id)
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
    get_pid().delete_run(run_id)
    return {"status": "deleted"}


class TagsTable(BaseModel):
    headers: list[str]
    rows: list[dict[str, str]]


def run_tags(run_id: str) -> tuple[RunInfo, list[SheetResult], TagsTable]:
    run, sheets = _run(run_id)
    if run.status in ("queued", "running"):
        raise HTTPException(409, "The run hasn't finished yet.")
    headers, rows = tags_table(sheets)
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
    # JSON only: forces a CORS preflight, so a cross-site page can't trigger a file write.
    if not request.headers.get("content-type", "").startswith("application/json"):
        raise HTTPException(415, "Expected application/json")
    run, sheets, _ = run_tags(run_id)
    title = f"P&ID tags from {len({s.file_name for s in sheets})} drawing(s), run {run.finished_at:%Y-%m-%d %H:%M}"
    data = tags_csv(sheets) if body.format == "csv" else tags_xlsx(sheets, title)
    if body.path is None:
        return Response(data, media_type=MEDIA[body.format],
                        headers={"Content-Disposition": f'attachment; filename="pid-tags.{body.format}"'})
    target = Path(body.path)
    if target.suffix.lower() != f".{body.format}":
        target = target.with_suffix(f".{body.format}")
    try:
        target.write_bytes(data)
    except OSError as exc:
        raise HTTPException(409, f"Could not save {target.name}: {exc.strerror or exc}. Is it open in Excel?") from exc
    return {"path": str(target)}
