# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""PID Symbols: the Project Master List of the symbols found on the P&IDs, one row per
detection, with where it is (x / y: its centre in mm from the sheet's top-left).

It is made from every PID Symbols (PSL) List Import: each one's latest revision (sent from a
Symbol Detection run) through its rules and mapping. It is read-only here: it changes when a
detection run is sent to the import again, or when the import's rules change.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from workbench_core.mel import output_list, run_pipeline
from workbench_core.mel.models import PID_SYMBOL_FIELDS

from .storage import get_store

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
