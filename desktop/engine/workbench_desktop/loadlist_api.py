# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""The project Load List: the MEL and EEL imports' rows, combined and live, each with a
plant area and a load type allocated (see workbench_core.keylists.loadlist)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from workbench_core.keylists import EEL_SOURCE, LOAD_LIST_TARGETS, EelList, LoadListRow, match_index
from workbench_core.keylists.loadlist import CABLE_CONSTRUCTIONS, CABLE_FIELDS
from workbench_core.mel import run_pipeline
from workbench_core.mel.models import ELEC_LOAD_FIELDS
from workbench_core.mel.pipeline import output_list
from workbench_core.refdata import RefValidationError, name_key

from .refdata_api import invalid
from .storage import NotFound, get_keylists, get_loadlist, get_store

router = APIRouter(prefix="/api/loadlist", tags=["load list"])


class Choice(BaseModel):
    id: str
    label: str
    depth: int = 0  # plant areas: the level in the tree (0 = top)


class Source(BaseModel):
    id: str
    name: str
    target: str
    rows: int
    has_file: bool


class LoadListView(BaseModel):
    fields: list[str]  # mapped load-list fields, in load-list order
    rows: list[LoadListRow]
    sources: list[Source]
    plant_areas: list[Choice]
    load_types: list[Choice]
    cable_insulations: list[str] = []  # the choices for a load's cable, from the Cable Types list
    cable_sizes: list[str] = []
    earth_sizes: list[str] = []
    warnings: list[str] = Field(default_factory=list)


def _choices() -> tuple[list[Choice], list[Choice]]:
    lists = get_keylists()
    nodes = lists.plant_areas().nodes  # parents first
    depth: dict[str, int] = {}
    for n in nodes:
        depth[n.id] = depth[n.parent_id] + 1 if n.parent_id in depth else 0
    areas = [Choice(id=n.id, label=f"{n.tag} – {n.description}", depth=depth[n.id]) for n in nodes]
    types = [Choice(id=t.id, label=f"{t.code} – {t.name}") for t in lists.load_types().items]
    return areas, types


EEL_NAME = "Electrical Equipment List"
EEL_GONE = "Deleted from the Electrical Equipment List"


def import_rows() -> tuple[list[LoadListRow], dict[str, str], list[Source], list[str]]:
    """The MEL and EEL imports' rows as they are now: (live rows, gone, sources, warnings).
    `gone`: import id -> why its remembered rows that aren't live are deleted (see
    LoadListStore.sync); it covers every import and every remembered import but the EEL list."""
    st = get_store()
    live: list[LoadListRow] = []
    gone: dict[str, str] = {}
    sources: list[Source] = []
    warnings: list[str] = []
    recipes = st.list_recipes()
    for info in recipes:
        rid = info["id"]
        if info["target"] not in LOAD_LIST_TARGETS:
            gone[rid] = "Its import is no longer a MEL or EEL import"
            continue
        recipe = st.get_recipe(rid)
        rev = st.latest_revision(rid)
        if rev is None:
            gone[rid] = "Its import has no file"
            sources.append(Source(id=rid, name=recipe.name, target=recipe.target, rows=0, has_file=False))
            continue
        result = run_pipeline(rev, recipe)
        out = output_list(result, recipe)
        warnings += [f"{recipe.name}: {i.rule}: {i.message}" for i in result.issues]
        warnings += [f"{recipe.name}: {w}" for w in out.warnings]
        for prow, values in zip(result.rows, out.rows):
            marked = values.get("is_deleted") is True
            live.append(LoadListRow(recipe_id=rid, key=prow.key, source=recipe.name, target=recipe.target, values=values,
                                    status="deleted" if marked else "active",
                                    deleted_reason="Marked deleted in the file" if marked else ""))
        gone[rid] = "Not in the latest file"
        sources.append(Source(id=rid, name=recipe.name, target=recipe.target, rows=len(out.rows), has_file=True))
    known = {info["id"] for info in recipes} | {EEL_SOURCE}
    for r in get_loadlist().rows():
        if r.recipe_id not in known:
            gone[r.recipe_id] = "Its import was deleted"
    return live, gone, sources, warnings


def eel_rows(eel: EelList) -> list[LoadListRow]:
    """The Electrical Equipment List's items as Load List rows: its allocations are its own ("eel")."""
    lists = get_keylists()
    codes = {c.id: c.code for c in lists.code_list("equipment-codes").items}
    rows = []
    for i in eel.items:
        values = {"tag": i.tag, "desc": i.description, "equip_type": codes.get(i.equipment_code_id, ""),
                  "load_rating": float(i.rating) if i.rating is not None and "." in i.rating else
                  (int(i.rating) if i.rating is not None else None),
                  "load_units": i.rating_unit, "load_voltage": i.voltage, "phases": i.phases}
        by = lambda v: "eel" if v not in (None, False) else None  # noqa: E731
        rows.append(LoadListRow(
            recipe_id=EEL_SOURCE, key=i.id, source=EEL_NAME, target="EEL", values=values,
            plant_area_id=i.plant_area_id, plant_area_by=by(i.plant_area_id),
            load_type_id=i.load_type_id, load_type_by=by(i.load_type_id),
            is_panel=i.is_panel, is_panel_by="eel", supplied_from=i.supplied_from, supplied_from_by=by(i.supplied_from)))
    return rows


def sync_rows(live: list[LoadListRow], gone: dict[str, str]) -> list[LoadListRow]:
    lists = get_keylists()
    area_index = match_index([(n.id, n.tag) for n in lists.plant_areas().nodes])
    type_index = match_index([(t.id, t.code) for t in lists.load_types().items])
    return get_loadlist().sync(live, gone, area_index, type_index)


def current_rows() -> tuple[list[LoadListRow], list[Source], list[str]]:
    """The Load List as it is now, brought up to date with the imports and the Electrical
    Equipment List: (rows, sources, warnings)."""
    live, gone, sources, warnings = import_rows()
    eel = get_keylists().eel()
    live += eel_rows(eel)
    gone[EEL_SOURCE] = EEL_GONE
    if eel.items:
        sources.append(Source(id=EEL_SOURCE, name=EEL_NAME, target="EEL", rows=len(eel.items), has_file=True))
    return sync_rows(live, gone), sources, warnings


@router.get("", response_model=LoadListView)
def load_list() -> LoadListView:
    rows, sources, warnings = current_rows()
    areas, types = _choices()

    used = {f for r in rows for f in r.values}
    tags: dict[str, tuple[str, list[str]]] = {}
    for r in rows:
        tag = r.values.get("tag")
        if r.status == "active" and isinstance(tag, str) and tag.strip():
            tags.setdefault(tag.strip().casefold(), (tag.strip(), []))[1].append(r.source)
    for tag, sources_of in (t for t in tags.values() if len(t[1]) > 1):
        warnings.append(f"Tag {tag} is in more than one row ({', '.join(sorted(set(sources_of)))}).")
    cables = get_keylists().cable_types().items

    def sizes(of: list) -> list[str]:
        numbers = {c.diameter for c in of if c.diameter.replace(".", "", 1).isdigit()}
        return sorted(numbers, key=float)
    return LoadListView(fields=[f for f in ELEC_LOAD_FIELDS if f in used], rows=rows, sources=sources,
                        plant_areas=areas, load_types=types, warnings=sorted(set(warnings)),
                        cable_insulations=sorted({c.insulation for c in cables if c.insulation}),
                        cable_sizes=sizes([c for c in cables if name_key(c.application) != "earth"]),
                        earth_sizes=sizes([c for c in cables if name_key(c.application) == "earth"]))


class RowRef(BaseModel):
    recipe_id: str
    key: str


class Allocation(BaseModel):
    """Rows, and what to give them: a plant area and/or load type (null = not allocated),
    whether they are distribution panels, and what supplies them ("primary" = the primary
    supply, a panel row's "<import id>/<key>", or null = not set). A field left out is not changed."""
    rows: list[RowRef]
    plant_area_id: str | None = None
    load_type_id: str | None = None
    is_panel: bool = False
    supplied_from: str | None = None
    # The power cable's details (typed in; null / blank = not set). Any row, the Electrical Equipment List's too.
    cable_length: float | None = None
    cable_construction: str | None = None
    cable_parallel: int | None = None
    cable_insulation: str = ""
    cable_size: str = ""
    earth_size: str = ""


def _check_cable(change: dict[str, object]) -> None:
    """The cable details as sent: tidied in place; raises RefValidationError for a bad one."""
    errors: dict[str, str] = {}
    cables = get_keylists().cable_types().items
    for f in ("cable_insulation", "cable_size", "earth_size"):
        if f in change:
            change[f] = str(change[f] or "").strip()
    length, parallel, kind = change.get("cable_length"), change.get("cable_parallel"), change.get("cable_construction")
    if length is not None and length < 0:
        errors["cable_length"] = "Can't be negative"
    if parallel is not None and parallel < 1:
        errors["cable_parallel"] = "1 or more"
    if "cable_construction" in change:
        change["cable_construction"] = next((c for c in CABLE_CONSTRUCTIONS if name_key(c) == name_key(str(kind or ""))), None)
        if kind and change["cable_construction"] is None:
            errors["cable_construction"] = "Multicore or Single core"
    if change.get("cable_insulation"):
        known = {name_key(c.insulation): c.insulation for c in cables if c.insulation}
        if name_key(change["cable_insulation"]) not in known:
            errors["cable_insulation"] = "Not an insulation in Cable Types"
        else:
            change["cable_insulation"] = known[name_key(change["cable_insulation"])]
    earth = {name_key(c.diameter) for c in cables if name_key(c.application) == "earth"}
    if change.get("cable_size") and name_key(change["cable_size"]) not in {name_key(c.diameter) for c in cables}:
        errors["cable_size"] = "Not a size in Cable Types"
    if change.get("earth_size") and name_key(change["earth_size"]) not in earth:
        errors["earth_size"] = "Not an earth cable size in Cable Types"
    if errors:
        raise RefValidationError("The cable details are not valid: " + "; ".join(f"{k.replace('_', ' ')}: {v}" for k, v in errors.items()) + ".", errors)


@router.put("/allocations", response_model=list[LoadListRow])
def allocate(body: Allocation):
    change = {f: getattr(body, f) for f in ("plant_area_id", "load_type_id", "is_panel", "supplied_from") + CABLE_FIELDS
              if f in body.model_fields_set}
    if not change or not body.rows:
        return invalid(RefValidationError("Choose rows and what to change."))
    areas, types = _choices()
    known = {"plant_area_id": {a.id for a in areas}, "load_type_id": {t.id for t in types}}
    for field, value in change.items():
        if field in known and value is not None and value not in known[field]:
            what = "plant area" if field == "plant_area_id" else "load type"
            return invalid(RefValidationError(f"That {what} no longer exists. Open the Load List again.", {field: "Not found"}))
    labels = {c.id: c.label for c in areas + types}
    try:
        _check_cable(change)
        return get_loadlist().allocate([(r.recipe_id, r.key) for r in body.rows], change, labels)
    except RefValidationError as exc:
        return invalid(exc)
    except NotFound as exc:
        raise HTTPException(404, "A row is no longer in the Load List. Open it again.") from exc


# -- the MEL: every row of the MEL imports, to read ---------------------------------------------

class MelRow(BaseModel):
    source: str  # the import's name
    recipe_id: str
    key: str  # the import's key column value
    tag: str  # the mapped tag when the import maps one, else the key
    in_load_list: bool  # False: unticked in the import's Rows step (not a load)
    values: dict[str, str]


class MelList(BaseModel):
    headers: list[str]  # the files' columns, every import's, in the order first seen
    rows: list[MelRow]
    sources: list[Source]
    warnings: list[str] = Field(default_factory=list)


def mel_list() -> MelList:
    """The whole MEL: every row of the latest file of every MEL import, after the import's
    column rules and before any row is unticked. So equipment that is not a load (a chute, a
    bin, a conveyor) is in it, marked as not in the Load List. It is read-only: it changes
    when an import's file or rules do."""
    st = get_store()
    headers: list[str] = []
    rows: list[MelRow] = []
    sources: list[Source] = []
    warnings: list[str] = []
    for info in st.list_recipes():
        if info["target"] != "MEL":
            continue
        recipe = st.get_recipe(info["id"])
        rev = st.latest_revision(info["id"])
        if rev is None:
            sources.append(Source(id=recipe.id, name=recipe.name, target=recipe.target, rows=0, has_file=False))
            continue
        result = run_pipeline(rev, recipe, upto="columns")
        warnings += [f"{recipe.name}: {i.rule}: {i.message}" for i in result.issues]
        headers += [h for h in result.headers if h not in headers]
        hidden = {h.key for h in recipe.hidden_rows}
        tag_column = next((m.column for m in recipe.mapping if m.field == "tag" and m.column), None)
        for r in result.rows:
            tag = (r.values.get(tag_column or "") or "").strip() or r.key
            rows.append(MelRow(source=recipe.name, recipe_id=recipe.id, key=r.key, tag=tag, in_load_list=r.key not in hidden,
                               values=r.values))
        sources.append(Source(id=recipe.id, name=recipe.name, target=recipe.target, rows=len(result.rows), has_file=True))
    return MelList(headers=headers, rows=rows, sources=sources, warnings=sorted(set(warnings)))


def mel_tags() -> list[str]:
    """Every tag of the MEL (a row's mapped tag, and its key), for lists that refer to equipment."""
    out: dict[str, str] = {}
    for r in mel_list().rows:
        for t in (r.tag, r.key):
            if name_key(t):
                out.setdefault(name_key(t), t.strip())
    return list(out.values())


mel_router = APIRouter(prefix="/api/mel-list", tags=["MEL"])


@mel_router.get("", response_model=MelList)
def get_mel_list() -> MelList:
    return mel_list()


# -- reset -----------------------------------------------------------------------------------------

class ResetBody(BaseModel):
    """What to reset: "all" (forget every row and read the imports again), or any of
    "plant_area", "load_type", "supply", "cable", "deleted"."""
    parts: list[str] = Field(default_factory=lambda: ["all"])


class ResetResult(BaseModel):
    message: str
    counts: dict[str, int]
    rows: int  # active rows after the imports were read again


@router.post("/reset", response_model=ResetResult)
def reset(body: ResetBody):
    """Reset the Load List, or parts of it, then read the imports again so that everything the
    files give is filled in automatically. The imports' files, rules and mappings are not touched."""
    store = get_loadlist()
    parts = set(body.parts)
    unknown = parts - set(store.RESET_PARTS) - {"all"}
    if unknown or not parts:
        return invalid(RefValidationError("Choose what to reset."))
    counts = store.reset(parts)
    rows = sum(1 for r in current_rows()[0] if r.status == "active")
    said = {"all": "{n} remembered row(s) forgotten", "plant_area": "{n} plant area(s) cleared", "load_type": "{n} load type(s) cleared",
            "supply": "panel and supply choices cleared on {n} row(s)", "cable": "cable details cleared on {n} row(s)",
            "deleted": "{n} deleted row(s) removed"}
    done = [said[k].format(n=n) for k, n in counts.items()] or ["Nothing needed resetting"]
    return ResetResult(message="; ".join(done) + f". The imports were read again: {rows} row(s).", counts=counts, rows=rows)
