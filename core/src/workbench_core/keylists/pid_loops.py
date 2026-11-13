# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""The Loops view of the PID Symbols list: its detections grouped by loop number, each loop with
its tags, function codes and the drawings it is on, and the instrument type it is (Instrument
Types). The type is suggested from the loop's functions until a person chooses one; a person
also ticks a loop as verified. Those choices are kept by loop number (`PidLoopStates`), so they
stay when the drawings are analysed again.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from .instrument_types import InstrumentType, suggest_type


class PidLoopState(BaseModel):
    """What a person decided about a loop."""
    type_id: str | None = None  # their choice of instrument type (None: not chosen, or "none" chosen: see no_type)
    no_type: bool = False  # they chose "no type"
    verified: bool = False
    verified_by: str = ""
    verified_at: datetime | None = None


class PidLoopStates(BaseModel):
    loops: dict[str, PidLoopState] = Field(default_factory=dict)  # loop number -> state
    updated_at: datetime | None = None


class PidLoop(BaseModel):
    loop: str
    functions: list[str]  # its tags' function codes, sorted
    tags: list[str]  # sorted
    drawings: list[str]  # "file p<page>", sorted
    detections: int
    type_id: str | None  # the type it has: chosen, else suggested
    type_name: str = ""
    type_by: Literal["user", "auto"] | None = None
    suggested_id: str | None = None
    verified: bool = False
    verified_by: str = ""
    verified_at: datetime | None = None


def _sort_key(text: str):
    """Natural order: 1023 before 1100, 99 before 100, text after numbers."""
    return [(0, int(p), "") if p.isdigit() else (1, 0, p.casefold()) for p in re.findall(r"\d+|\D+", text)]


def loops_of(rows: list[dict], types: list[InstrumentType], states: PidLoopStates) -> list[PidLoop]:
    """Group the PID Symbols rows (pid_symbols_api: tag, function, loop, drawing, page…) by loop
    number, in natural order. Rows with no loop number are left out."""
    groups: dict[str, dict] = {}
    for r in rows:
        loop = str(r.get("loop") or "").strip()
        if not loop:
            continue
        g = groups.setdefault(loop, {"functions": set(), "tags": set(), "drawings": set(), "n": 0})
        g["n"] += 1
        fn = str(r.get("function") or "").strip().upper()
        if fn:
            g["functions"].add(fn)
        tag = str(r.get("tag") or "").strip()
        if tag:
            g["tags"].add(tag)
        drawing = str(r.get("drawing") or "").strip()
        if drawing:
            page = r.get("page")
            g["drawings"].add(f"{drawing} p{int(page) if isinstance(page, (int, float)) else page}" if page not in (None, "") else drawing)
    by_id = {t.id: t for t in types}
    out = []
    for loop in sorted(groups, key=_sort_key):
        g = groups[loop]
        functions = sorted(g["functions"])
        suggested = suggest_type(functions, types)
        st = states.loops.get(loop, PidLoopState())
        chosen = by_id.get(st.type_id or "")
        if st.no_type:
            t, by = None, "user"
        elif chosen is not None:
            t, by = chosen, "user"
        else:
            t, by = suggested, ("auto" if suggested else None)
        out.append(PidLoop(loop=loop, functions=functions, tags=sorted(g["tags"], key=_sort_key),
                           drawings=sorted(g["drawings"], key=_sort_key), detections=g["n"], type_id=t.id if t else None,
                           type_name=t.name if t else "", type_by=by, suggested_id=suggested.id if suggested else None,
                           verified=st.verified, verified_by=st.verified_by, verified_at=st.verified_at))
    return out


__all__ = ["PidLoopState", "PidLoopStates", "PidLoop", "loops_of"]
