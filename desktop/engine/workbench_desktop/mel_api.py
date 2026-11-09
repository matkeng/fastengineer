"""MEL import endpoints: recipes, file revisions, the pipeline, export."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from workbench_core.excel import ExcelError
from workbench_core.mel import (
    IngestError,
    PipelineResult,
    Recipe,
    fields_for,
    output_list,
    output_name,
    parse_csv,
    rows_from_extract,
    run_pipeline,
    unique_keys,
)
from workbench_core.mel.export import combined_csv, combined_xlsx, load_list_csv, load_list_xlsx
from workbench_core.mel.models import RevisionInfo, TargetList
from workbench_core.mel.pipeline import LoadListResult, Stage

from .excel_api import ExtractRequest
from .excel_api import store as workbooks
from .storage import NotFound, get_store

router = APIRouter(prefix="/api/mel", tags=["mel"])
MAX_UPLOAD = 100 * 1024 * 1024
KEY_HINTS = re.compile(r"\b(tag|id|no\.?|number|key|item)\b", re.I)


def _recipe(recipe_id: str) -> Recipe:
    try:
        return get_store().get_recipe(recipe_id)
    except NotFound as exc:
        raise HTTPException(404, "Import recipe not found.") from exc


def _latest(recipe_id: str):
    rev = get_store().latest_revision(recipe_id)
    if rev is None:
        # PRD 11 item 4: a recipe with no file must not crash every page.
        raise HTTPException(409, "Upload a file first: this import has no file yet.")
    return rev


# -- recipes -----------------------------------------------------------------

class NewRecipe(BaseModel):
    name: str
    target: TargetList = "MEL"


class RecipeDetail(BaseModel):
    recipe: Recipe
    revisions: list[RevisionInfo]
    fields: list[str]  # what the recipe's target maps onto
    output_name: str  # "Load list" (MEL) or "Instrument list" (PIL)


@router.get("/storage")
def storage_info() -> dict[str, str]:
    """Where saved imports live (shown on the Engine tab, for backups)."""
    return {"path": str(get_store().path)}


@router.get("/recipes")
def list_recipes() -> list[dict]:
    return get_store().list_recipes()


@router.post("/recipes", response_model=Recipe)
def create_recipe(body: NewRecipe) -> Recipe:
    return get_store().create_recipe(body.name, body.target)


@router.get("/recipes/{recipe_id}", response_model=RecipeDetail)
def get_recipe(recipe_id: str) -> RecipeDetail:
    recipe = _recipe(recipe_id)
    return RecipeDetail(recipe=recipe, revisions=get_store().list_revisions(recipe_id),
                        fields=fields_for(recipe.target), output_name=output_name(recipe.target))


@router.put("/recipes/{recipe_id}", response_model=Recipe)
def save_recipe(recipe_id: str, recipe: Recipe) -> Recipe:
    if recipe.id != recipe_id:
        raise HTTPException(400, "Recipe id mismatch.")
    try:
        return get_store().save_recipe(recipe)
    except NotFound as exc:
        raise HTTPException(404, "Import recipe not found.") from exc


@router.delete("/recipes/{recipe_id}")
def delete_recipe(recipe_id: str) -> dict[str, str]:
    get_store().delete_recipe(recipe_id)
    return {"status": "deleted"}


# -- files -------------------------------------------------------------------

class CsvInspect(BaseModel):
    headers: list[str]
    headers_original: list[str]
    num_rows: int
    sample: list[dict[str, str]]
    suggested_key: str
    warnings: list[str]


def _suggest_key(headers: list[str], rows: list[dict[str, str]]) -> str:
    def score(i_h: tuple[int, str]) -> float:
        i, h = i_h
        values = [r.get(h, "").strip() for r in rows]
        filled = [v for v in values if v]
        unique = len(Counter(filled)) / max(len(rows), 1)
        return unique + 0.3 * bool(KEY_HINTS.search(h)) - 0.05 * i
    return max(enumerate(headers), key=score)[1]


async def _body(request: Request) -> bytes:
    data = await request.body()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "The file is larger than 100 MB.")
    return data


@router.post("/csv/inspect", response_model=CsvInspect)
async def inspect_csv(request: Request) -> CsvInspect:
    """Read a CSV's headers so the user can choose the key column (PRD 5.1 step 2)."""
    data = await _body(request)
    try:
        original, headers, rows, warnings = await run_in_threadpool(parse_csv, data)
    except IngestError as exc:
        raise HTTPException(400, str(exc)) from exc
    return CsvInspect(headers=headers, headers_original=original, num_rows=len(rows), sample=rows[:5],
                      suggested_key=_suggest_key(headers, rows), warnings=warnings)


def _add(recipe_id: str, file_name: str, source: str, key: str, original, headers, rows, warnings):
    if key not in headers:
        raise HTTPException(400, f"Key column '{key}' is not in the file.")
    changed = unique_keys(rows, key)
    if changed:
        warnings = [*warnings, f"{changed} key value(s) were blank or repeated and were made unique "
                               "(blank -> 'Blank', repeats -> '_1', '_2')."]
    rows.sort(key=lambda r: r[key])
    _recipe(recipe_id)
    return get_store().add_revision(recipe_id, file_name, source, key, original, headers, rows, warnings)


@router.post("/recipes/{recipe_id}/revisions/csv", response_model=RevisionInfo)
async def upload_csv(recipe_id: str, request: Request, filename: str = Query(...), key: str = Query(...)):
    data = await _body(request)
    try:
        original, headers, rows, warnings = await run_in_threadpool(parse_csv, data)
    except IngestError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _add(recipe_id, filename, "csv", key, original, headers, rows, warnings)


class ExcelSource(ExtractRequest):
    workbook_id: str


@router.post("/recipes/{recipe_id}/revisions/excel", response_model=RevisionInfo)
def upload_excel(recipe_id: str, body: ExcelSource) -> RevisionInfo:
    wb = workbooks.get(body.workbook_id)
    try:
        ex = wb.extract(body.source, body.header_row, body.key_column,
                        header_rows=body.header_rows, skip_blank_keys=body.skip_blank_keys)
    except ExcelError as exc:
        raise HTTPException(400, str(exc)) from exc
    original, headers, rows = rows_from_extract(ex)
    key = headers[body.key_column]
    return _add(recipe_id, wb.filename, f"excel: {ex.source.name}", key, original, headers, rows, list(ex.warnings))


class SymbolsSource(BaseModel):
    run_id: str


@router.post("/recipes/{recipe_id}/revisions/symbols", response_model=RevisionInfo)
def upload_symbols(recipe_id: str, body: SymbolsSource) -> RevisionInfo:
    """Add the tags list from a finished symbol-detection run as a new revision."""
    from .symbols_api import run_tags
    run, sheets, table = run_tags(body.run_id)
    if not table.rows:
        raise HTTPException(400, "That run found no tags, so there is nothing to import.")
    drawings = len({s.file_name for s in sheets})
    name = f"Tags {run.finished_at:%Y-%m-%d %H:%M}" if run.finished_at else "Tags"
    rows = [dict(r) for r in table.rows]
    return _add(recipe_id, name, f"symbols: {drawings} drawing(s), {len(sheets)} sheet(s)", "Tag",
                list(table.headers), list(table.headers), rows, list(run.warnings[:20]))


@router.delete("/recipes/{recipe_id}/revisions/{revision_id}")
def delete_revision(recipe_id: str, revision_id: str) -> dict[str, str]:
    get_store().delete_revision(recipe_id, revision_id)
    return {"status": "deleted"}


# -- pipeline ----------------------------------------------------------------

class RunRequest(BaseModel):
    stage: Stage = "auto"
    recipe: Recipe | None = None  # unsaved edits to preview; default: the saved recipe


def _draft(recipe_id: str, draft: Recipe | None) -> Recipe:
    return draft if draft is not None else _recipe(recipe_id)


@router.post("/recipes/{recipe_id}/run", response_model=PipelineResult)
def run(recipe_id: str, body: RunRequest) -> PipelineResult:
    return run_pipeline(_latest(recipe_id), _draft(recipe_id, body.recipe), body.stage)


@router.post("/recipes/{recipe_id}/loadlist", response_model=LoadListResult)
def loadlist(recipe_id: str, body: RunRequest) -> LoadListResult:
    recipe = _draft(recipe_id, body.recipe)
    return output_list(run_pipeline(_latest(recipe_id), recipe), recipe)


class ExportRequest(BaseModel):
    table: Literal["combined", "loadlist"] = "combined"
    format: Literal["csv", "xlsx"] = "xlsx"
    recipe: Recipe | None = None
    path: str | None = None  # desktop: chosen in a Save As dialog


MEDIA = {"csv": "text/csv", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}


@router.post("/recipes/{recipe_id}/export")
def export(recipe_id: str, body: ExportRequest, request: Request):
    # JSON only: forces a CORS preflight, so a cross-site page can't trigger a file write.
    if not request.headers.get("content-type", "").startswith("application/json"):
        raise HTTPException(415, "Expected application/json")
    recipe = _draft(recipe_id, body.recipe)
    rev = _latest(recipe_id)
    result = run_pipeline(rev, recipe)
    title = f"{recipe.name} ({recipe.target}) from {rev.file_name} rev {rev.rev}"
    if body.table == "combined":
        auto = [a.name for a in recipe.auto_columns]
        data = combined_csv(result) if body.format == "csv" else combined_xlsx(result, auto, title)
    else:
        ll = output_list(result, recipe)
        data = load_list_csv(ll) if body.format == "csv" else load_list_xlsx(ll, result, title, output_name(recipe.target))
    if body.path is None:
        name = f"{recipe.target}-{body.table}.{body.format}"
        return Response(data, media_type=MEDIA[body.format],
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})
    target = Path(body.path)
    if target.suffix.lower() != f".{body.format}":
        target = target.with_suffix(f".{body.format}")
    try:
        target.write_bytes(data)
    except OSError as exc:
        raise HTTPException(409, f"Could not save {target.name}: {exc.strerror or exc}. Is it open in Excel?") from exc
    return {"path": str(target)}
