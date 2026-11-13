# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""PID Symbols: the Project Master List of the symbols found on the P&IDs, one row per
detection, with where it is (x / y: its centre in mm from the sheet's top-left).

It is made from every PID Symbols (PSL) List Import: each one's latest revision (sent from a
Symbol Detection run) through its rules and mapping. It is read-only here: it changes when a
detection run is sent to the import again, or when the import's rules change.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from workbench_core.keylists.pid_loops import PidLoop, PidLoopState, loops_of
from workbench_core.mel import output_list, run_pipeline
from workbench_core.mel.models import PID_SYMBOL_FIELDS
from workbench_core.refdata import RefValidationError

from . import identity
from .refdata_api import invalid
from .storage import get_keylists, get_store

router = APIRouter(prefix="/api/pid-symbols", tags=["pid symbols"])


class PidSource(BaseModel):
    id: str
    name: str
    rows: int
    has_file: bool


class PidSymbolsView(BaseModel):
    fields: list[str]  # the mapped fields, in order
    rows: list[dict[str, str | float | int | bool | None]]  # each with "import" (its name), "recipe_id" and "key" too
    sources: list[PidSource]
    warnings: list[str] = Field(default_factory=list)


def pid_symbols() -> PidSymbolsView:
    st = get_store()
    fields: set[str] = set()
    rows: list[dict] = []
    sources: list[PidSource] = []
    warnings: list[str] = []
    for info in st.list_recipes():
        if info["target"] != "PSL":
            continue
        recipe = st.get_recipe(info["id"])
        rev = st.latest_revision(info["id"])
        if rev is None:
            sources.append(PidSource(id=recipe.id, name=recipe.name, rows=0, has_file=False))
            continue
        result = run_pipeline(rev, recipe)
        out = output_list(result, recipe)
        warnings += [f"{recipe.name}: {i.rule}: {i.message}" for i in result.issues] + [f"{recipe.name}: {w}" for w in out.warnings]
        fields |= set(out.fields)
        for r, values in zip(result.rows, out.rows):
            rows.append({**values, "import": recipe.name, "recipe_id": recipe.id, "key": r.key})
        sources.append(PidSource(id=recipe.id, name=recipe.name, rows=len(out.rows), has_file=True))
    return PidSymbolsView(fields=[f for f in PID_SYMBOL_FIELDS if f in fields], rows=rows, sources=sources,
                          warnings=sorted(set(warnings)))


@router.get("", response_model=PidSymbolsView)
def get_pid_symbols() -> PidSymbolsView:
    return pid_symbols()


# -- the Loops view: detections grouped by loop number -------------------------------------------

class TypeChoice(BaseModel):
    id: str
    name: str
    functions: list[str]


class LoopsView(BaseModel):
    loops: list[PidLoop]
    types: list[TypeChoice]
    without_loop: int  # detections with no loop number (not in any loop)


@router.get("/loops", response_model=LoopsView)
def get_loops() -> LoopsView:
    lists = get_keylists()
    rows = pid_symbols().rows
    types = lists.instrument_types().items
    return LoopsView(loops=loops_of(rows, types, lists.pid_loops()),
                     types=[TypeChoice(id=t.id, name=t.name, functions=t.functions) for t in types],
                     without_loop=sum(1 for r in rows if not str(r.get("loop") or "").strip()))


class LoopChange(BaseModel):
    """What to change about a loop; a field left out is kept. type_id: an instrument type's id,
    "" for no type, or null to go back to the suggested one."""
    type_id: str | None = None
    verified: bool | None = None


@router.put("/loops/{loop}", response_model=PidLoop)
def update_loop(loop: str, body: LoopChange):
    lists = get_keylists()
    types = lists.instrument_types().items
    rows = pid_symbols().rows
    if not any(str(r.get("loop") or "").strip() == loop for r in rows):
        raise HTTPException(404, f"Loop {loop} is not in the PID Symbols list.")
    state = lists.pid_loops().loops.get(loop, PidLoopState()).model_copy()
    if "type_id" in body.model_fields_set:
        if body.type_id is None:
            state.type_id, state.no_type = None, False
        elif body.type_id == "":
            state.type_id, state.no_type = None, True
        elif body.type_id not in {t.id for t in types}:
            return invalid(RefValidationError("That instrument type no longer exists. Open the list again.", {"type_id": "Not found"}))
        else:
            state.type_id, state.no_type = body.type_id, False
    if body.verified is not None and body.verified != state.verified:
        state.verified = body.verified
        state.verified_by = identity.current().user if body.verified else ""
        state.verified_at = datetime.now(timezone.utc) if body.verified else None
    states = lists.save_pid_loop(loop, state)
    return next(x for x in loops_of(rows, types, states) if x.loop == loop)
