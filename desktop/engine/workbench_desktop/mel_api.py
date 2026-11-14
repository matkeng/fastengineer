# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""MEL import endpoints: recipes, file revisions, the pipeline, export."""

from __future__ import annotations

import re
from collections import Counter
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
from workbench_core.mel.models import FieldMap, is_load_target
from workbench_core.mel.ingest import STRIKE_COLUMN, add_blank_strike_column
from workbench_core.mel.models import RevisionInfo, TargetList
from workbench_core.mel.pipeline import LoadListResult, Stage

from .exporting import save_to
from .uploads import read_upload
from .excel_api import ExtractRequest
from .excel_api import store as workbooks
from .storage import NotFound, get_keylists, get_store

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
    fields: list[str]  # what the recipe's target maps onto (keys)
    labels: dict[str, str] = {}  # field key -> what it is called (the project's Load List fields)
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
    lf = get_keylists().load_fields()
    load = is_load_target(recipe.target)
    return RecipeDetail(recipe=recipe, revisions=get_store().list_revisions(recipe_id),
                        fields=fields_for(recipe.target, lf.importable()),
                        labels=lf.labels() if load else _pid_labels() if recipe.target == "PSL" else {},
                        output_name=output_name(recipe.target))


def _pid_labels() -> dict[str, str]:
    from workbench_core.keylists.workbooks import PID_SYMBOL_HEADINGS
    return dict(PID_SYMBOL_HEADINGS)


def _refuse_not_allowed(recipe: Recipe) -> None:
    """Refuse calculated columns that use anything not allowed (see workbench_core.mel.functions)."""
    from workbench_core.mel.functions import auto_column_problems
    found = [f"{c.name}, {p}" for c in recipe.auto_columns for p in auto_column_problems(c)]
    if found:
        raise HTTPException(422, "A calculated column uses something that isn't allowed: " + "; ".join(found[:5])
                            + (f"; and {len(found) - 5} more" if len(found) > 5 else "") + ".")


@router.put("/recipes/{recipe_id}", response_model=Recipe)
def save_recipe(recipe_id: str, recipe: Recipe) -> Recipe:
    if recipe.id != recipe_id:
        raise HTTPException(400, "Recipe id mismatch.")
    _refuse_not_allowed(recipe)
    try:
        return get_store().save_recipe(recipe)
    except NotFound as exc:
        raise HTTPException(404, "Import recipe not found.") from exc


@router.delete("/recipes/{recipe_id}")
def delete_recipe(recipe_id: str) -> dict[str, str]:
    get_store().delete_recipe(recipe_id)
    return {"status": "deleted"}


# -- what a calculated column can use --------------------------------------------------------

class FunctionExample(BaseModel):
    expression: str
    result: str  # what the sample row gives (the tests check each one)
    what: str


class FunctionGroup(BaseModel):
    name: str
    about: str
    examples: list[FunctionExample]


class FunctionHelp(BaseModel):
    sample_row: dict[str, str]  # the row the examples are worked out on
    groups: list[FunctionGroup]
    functions: list[str]  # every function an expression can call: nothing else is allowed
    text_functions: list[str]  # every text function, written after a text value
    names: list[str]  # names besides the columns: True, False, None, pi, e


@router.get("/functions", response_model=FunctionHelp)
def function_help() -> FunctionHelp:
    """The text and number functions a calculated column can use, with worked examples."""
    from workbench_core.mel.functions import FUNCTION_HELP, FUNCTIONS, METHODS, NAMES, SAMPLE_ROW
    return FunctionHelp(sample_row=SAMPLE_ROW, groups=[
        FunctionGroup(name=name, about=about, examples=[FunctionExample(expression=e, result=r, what=w) for e, r, w in items])
        for name, about, items in FUNCTION_HELP], functions=sorted(FUNCTIONS), text_functions=list(METHODS), names=list(NAMES))


# -- the settings of an import as a file, to pass between people ----------------------------

SETTINGS_FORMAT = "drawing-workbench/list-import-settings"
#: What a person decides in an import: everything of the recipe but its id, name and the files.
SETTINGS = ("columns", "hidden_rows", "text_columns", "overrides", "custom_rows", "find_replace", "auto_columns", "mapping")


class SettingsBody(BaseModel):
    path: str | None = None  # desktop: chosen in a Save As dialog


def settings_document(recipe: Recipe) -> dict:
    return {"format": SETTINGS_FORMAT, "version": 1, "name": recipe.name, "target": recipe.target,
            "settings": recipe.model_dump(mode="json", include=set(SETTINGS))}


def _read_settings(doc: object) -> tuple[str, str, dict]:
    """(name, target, settings) of a settings file, checked. Raises HTTPException(422) saying what is wrong."""
    if not isinstance(doc, dict) or doc.get("format") != SETTINGS_FORMAT or not isinstance(doc.get("settings"), dict):
        raise HTTPException(422, "This is not a list import settings file (exported with Export settings).")
    if doc.get("version") != 1:
        raise HTTPException(422, "This settings file was made by a newer version of the app. Update the app to read it.")
    settings = {k: v for k, v in doc["settings"].items() if k in SETTINGS}
    try:
        checked = Recipe(id="check", name=str(doc.get("name") or "Imported settings"), target=doc.get("target") or "MEL", **settings)
    except ValueError as exc:  # pydantic's ValidationError
        raise HTTPException(422, f"The settings file is damaged: {str(exc).splitlines()[0]}.") from exc
    _refuse_not_allowed(checked)
    return checked.name, checked.target, checked.model_dump(include=set(SETTINGS))


@router.post("/recipes/{recipe_id}/settings/export")
def export_settings(recipe_id: str, body: SettingsBody, request: Request):
    """The saved settings of an import (its rules, hidden rows, overrides, added rows, calculated
    columns and mapping) as a JSON file. The uploaded files are not in it."""
    if not request.headers.get("content-type", "").startswith("application/json"):
        raise HTTPException(415, "Expected application/json")
    import json
    recipe = _recipe(recipe_id)
    data = json.dumps(settings_document(recipe), indent=2, ensure_ascii=False).encode("utf-8")
    if body.path is None:
        return Response(data, media_type="application/json",
                        headers={"Content-Disposition": 'attachment; filename="list-import-settings.json"'})
    return save_to(body.path, data, ".json")


@router.post("/recipes/{recipe_id}/settings/read", response_model=Recipe)
def read_settings(recipe_id: str, doc: dict) -> Recipe:
    """This import with a settings file's settings in place of its own. Nothing is saved: the
    caller shows it as unsaved changes. The file must be for the same kind of list."""
    recipe = _recipe(recipe_id)
    _, target, settings = _read_settings(doc)
    if target != recipe.target:
        raise HTTPException(422, f"These settings are for a {target} import; this one is a {recipe.target} import.")
    return Recipe.model_validate(recipe.model_dump() | settings)


@router.post("/settings/new", response_model=Recipe)
def new_from_settings(doc: dict) -> Recipe:
    """A new import with a settings file's name, kind of list and settings (and no file yet)."""
    name, target, settings = _read_settings(doc)
    st = get_store()
    taken = {r["name"].strip().casefold() for r in st.list_recipes()}
    unique, n = name, 2
    while unique.strip().casefold() in taken:
        unique, n = f"{name} ({n})", n + 1
    recipe = st.create_recipe(unique, target)
    return st.save_recipe(Recipe.model_validate(recipe.model_dump() | settings))


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
    data = await read_upload(request, MAX_UPLOAD)
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
    order = sorted(range(len(rows)), key=lambda i: rows[i][key])  # kept in key order; where each was is kept too
    _recipe(recipe_id)
    return get_store().add_revision(recipe_id, file_name, source, key, original, headers, [rows[i] for i in order], warnings,
                                    [i + 1 for i in order])


@router.post("/recipes/{recipe_id}/revisions/csv", response_model=RevisionInfo)
async def upload_csv(recipe_id: str, request: Request, filename: str = Query(...), key: str = Query(...)):
    data = await _body(request)
    try:
        original, headers, rows, warnings = await run_in_threadpool(parse_csv, data)
    except IngestError as exc:
        raise HTTPException(400, str(exc)) from exc
    if _recipe(recipe_id).target == "MEL":  # a MEL always has the Strike through column; a CSV has no formatting to fill it
        original, headers = add_blank_strike_column(original, rows)
        warnings = [*warnings, f"A CSV file has no formatting, so the {STRIKE_COLUMN} column is blank: "
                               "upload the Excel file to see which rows are struck through."]
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
    original, headers, rows = rows_from_extract(ex, strike=_recipe(recipe_id).target == "MEL")  # a MEL: + Strike through
    key = headers[body.key_column]
    return _add(recipe_id, wb.filename, f"excel: {ex.source.name}", key, original, headers, rows, list(ex.warnings))


class SymbolsSource(BaseModel):
    run_id: str


#: PID Symbols field -> the detections table's column (symbols.pipeline.detections_table).
PSL_COLUMNS = {"tag": "Tag", "symbol": "Symbol", "drawing": "Drawing", "page": "Page", "x_mm": "X (mm)", "y_mm": "Y (mm)",
               "width_mm": "Width (mm)", "height_mm": "Height (mm)", "score": "Score", "source": "Source"}


@router.post("/recipes/{recipe_id}/revisions/symbols", response_model=RevisionInfo)
def upload_symbols(recipe_id: str, body: SymbolsSource) -> RevisionInfo:
    """Add a finished symbol-detection run as a new revision: for a PID Symbols (PSL) import, one
    row per detection with its centre in mm (detections_table), and, while the import maps
    nothing yet, the matching columns mapped; for the others, the tags list (one row per tag)."""
    from workbench_core.symbols.pipeline import detections_table

    from .symbols_api import run_tags
    run, sheets, table = run_tags(body.run_id)
    recipe = _recipe(recipe_id)
    drawings = len({s.file_name for s in sheets})
    source = f"symbols: {drawings} drawing(s), {len(sheets)} sheet(s)"
    if recipe.target == "PSL":
        headers, rows = detections_table(sheets, run.columns)
        if not rows:
            raise HTTPException(400, "That run found no symbols or tags, so there is nothing to import.")
        name = f"Symbols {run.finished_at:%Y-%m-%d %H:%M}" if run.finished_at else "Symbols"
        info = _add(recipe_id, name, source, "Key", list(headers), list(headers), rows, list(run.warnings[:20]))
        if not recipe.mapping:
            cols = {**{c.casefold(): c for c in headers}, **{f: c for f, c in PSL_COLUMNS.items()}}
            mapping = [FieldMap(field=f, column=cols[f]) for f in fields_for("PSL") if f in cols and cols[f] in headers]
            get_store().save_recipe(_recipe(recipe_id).model_copy(update={"mapping": mapping}))
        return info
    if not table.rows:
        raise HTTPException(400, "That run found no tags, so there is nothing to import.")
    name = f"Tags {run.finished_at:%Y-%m-%d %H:%M}" if run.finished_at else "Tags"
    rows = [dict(r) for r in table.rows]
    return _add(recipe_id, name, source, "Tag", list(table.headers), list(table.headers), rows, list(run.warnings[:20]))


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
    return output_list(run_pipeline(_latest(recipe_id), recipe), recipe, get_keylists().load_fields())


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
        ll = output_list(result, recipe, get_keylists().load_fields())
        data = load_list_csv(ll) if body.format == "csv" else load_list_xlsx(ll, result, title, output_name(recipe.target))
    if body.path is None:
        name = f"{recipe.target}-{body.table}.{body.format}"
        return Response(data, media_type=MEDIA[body.format],
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})
    return save_to(body.path, data, f".{body.format}")


class ReportRequest(BaseModel):
    recipe: Recipe | None = None  # the import as it is in the editor (default: as saved)
    path: str | None = None  # desktop: chosen in a Save As dialog


@router.post("/recipes/{recipe_id}/edits-report")
def edits_report_file(recipe_id: str, body: ReportRequest, request: Request):
    """The edits the import makes to its latest file (changed cells, removed rows, added rows,
    with their reasons) as a workbook, to send back to whoever owns the file."""
    from workbench_core.keylists.workbooks import write_sheets
    from workbench_core.mel.edits_report import edits_report

    if not request.headers.get("content-type", "").startswith("application/json"):
        raise HTTPException(415, "Expected application/json")
    recipe = _draft(recipe_id, body.recipe)
    rev = _latest(recipe_id)
    data = write_sheets(edits_report(rev, recipe))
    name = re.sub(r'[\\/:*?"<>|]+', "_", f"{recipe.name} - edits to {rev.file_name} rev {rev.rev}") + ".xlsx"
    if body.path is None:
        from urllib.parse import quote
        plain = name.encode("ascii", "replace").decode().replace("?", "_")
        return Response(data, media_type=MEDIA["xlsx"], headers={
            "Content-Disposition": f"attachment; filename=\"{plain}\"; filename*=UTF-8''{quote(name)}"})
    return save_to(body.path, data, ".xlsx")


class EditsCheck(BaseModel):
    rev: int
    file_name: str
    edits: list[dict]  # mel.edits_report.EditStatus, in the order changed, removed, added


@router.post("/recipes/{recipe_id}/edits-check", response_model=EditsCheck)
def edits_check(recipe_id: str, body: ReportRequest) -> EditsCheck:
    """Whether the latest file has taken in each of the import's edits: those it has ("done"),
    and changed cells whose row has gone ("gone"), can be cleared."""
    from workbench_core.mel.edits_report import edits_status

    recipe = _draft(recipe_id, body.recipe)
    rev = _latest(recipe_id)
    return EditsCheck(rev=rev.rev, file_name=rev.file_name, edits=[e.model_dump() for e in edits_status(rev, recipe)])
