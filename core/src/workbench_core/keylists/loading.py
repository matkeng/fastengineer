# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Board loading: the demand of everything fed from each board, against the board's rating.

A board is a Load List row marked as a distribution panel (a switchboard, an MCC, a
transformer): the loads below it are the rows supplied from it, directly or through other
boards. For each load:

    connected kW    = its rating (kW; HP converted; Amps or kVA through its voltage and power factor)
    max demand kW   = connected kW x nameplate load factor x maximum demand factor
    average kW      = connected kW x nameplate load factor x average demand factor
    kVA             = kW / power factor (its motor's at full load; 0.85 when it has no motor)

A board's figures are the plain sums of its loads': there is no diversity between boards. Its
loading is its maximum demand over its own rating, in the rating's unit (kVA, kW or Amps).
"""

from __future__ import annotations

import math

from pydantic import BaseModel, Field

from .load_calcs import load_cells
from .loadgen import ordered
from .loadlist import PRIMARY_SUPPLY, LoadListRow
from .models import LoadType
from .units import rating_kw, unit_kind

#: The power factor of a load with no motor in Motor Data.
DEFAULT_PF = 0.85
#: A board at or above this loading (%) is flagged, unless another figure is asked for.
WARN_AT = 80.0


class LoadDemand(BaseModel):
    connected_kw: float = 0
    max_kw: float = 0
    avg_kw: float = 0
    max_kva: float = 0
    #: Why the load adds nothing ("" when it does): no rating, or units the app doesn't know.
    left_out: str = ""


class LeftOut(BaseModel):
    tag: str
    reason: str
    supplied_from: str = ""


class BoardLoading(BaseModel):
    ref: str
    tag: str
    description: str = ""
    depth: int = 0  # 0: fed from the primary supply (or from nothing); 1: fed from such a board…
    supplied_from: str = ""
    loads: int = 0  # the loads below it that count
    left_out: int = 0  # the loads below it that don't (see LoadingReport.left_out)
    connected_kw: float = 0
    max_kw: float = 0
    avg_kw: float = 0
    max_kva: float = 0
    max_amps: float | None = None  # at the board's voltage (None when it has none)
    rating: float | None = None
    rating_unit: str = ""  # "kVA", "kW" or "Amps" ("" when the board has no usable rating)
    loading_pct: float | None = None
    spare: float | None = None  # in the rating's unit
    over: bool = False  # at or above the warning level
    problem: str = ""


class LoadingReport(BaseModel):
    boards: list[BoardLoading] = Field(default_factory=list)
    left_out: list[LeftOut] = Field(default_factory=list)
    warn_at: float = WARN_AT
    default_pf: float = DEFAULT_PF


def _number(v: object) -> float | None:
    if isinstance(v, bool) or v in (None, ""):
        return None
    try:
        n = float(str(v).strip().replace(",", ""))
    except ValueError:
        return None
    return n if math.isfinite(n) else None


def _three_phase(phases: object) -> bool:
    """Three-phase unless the phases say single-phase or DC (blank: three-phase)."""
    p = str(phases or "").casefold()
    return not ("1-phase" in p or p.startswith("dc"))


def _dc(phases: object) -> bool:
    return str(phases or "").casefold().startswith("dc")


def _kva_of_amps(amps: float, volts: float, phases: object) -> float:
    return (math.sqrt(3) if _three_phase(phases) else 1) * volts * amps / 1000


def _factor(v: object) -> float:
    n = _number(v)
    return 1.0 if n is None else n  # no Load Factors row for it: taken at its full rating


def load_demand(cells: dict[str, object]) -> LoadDemand:
    """One load's demand, from what is known about it (load_calcs.load_cells)."""
    rating = _number(cells.get("rating"))
    if rating is None or rating <= 0:
        return LoadDemand(left_out="No rating")
    kind = unit_kind(cells.get("units"))
    if kind is None:
        return LoadDemand(left_out=f"Its units ({cells.get('units')}) are not kW, HP, Amps or kVA")
    pf = _number(cells.get("motor.pf100"))
    pf = 1.0 if _dc(cells.get("phases")) else pf if pf is not None and 0 < pf <= 1 else DEFAULT_PF
    if kind in ("kW", "HP"):
        kw = rating_kw(rating, cells.get("units")) or 0.0
    else:
        if kind == "Amps":
            volts = _number(cells.get("voltage"))
            if volts is None or volts <= 0:
                return LoadDemand(left_out="Rated in Amps with no voltage")
            kva = _kva_of_amps(rating, volts, cells.get("phases"))
        else:
            kva = rating
        kw = kva * pf
    nameplate = _factor(cells.get("loadfactor.nameplatelf"))
    max_kw = kw * nameplate * _factor(cells.get("loadfactor.maxdemand"))
    return LoadDemand(connected_kw=kw, max_kw=max_kw, avg_kw=kw * nameplate * _factor(cells.get("loadfactor.avgdemand")),
                      max_kva=max_kw / pf)


def board_loading(rows: list[LoadListRow], load_types: dict[str, LoadType], areas: dict[str, tuple[str, str]],
                  motors: list | None = None, drives: list | None = None, starters=None, load_factors: list | None = None,
                  warn_at: float = WARN_AT) -> LoadingReport:
    """Every board of the Load List with the demand of the loads below it, in supply order
    (a board, then the boards fed from it). Deleted rows are left out; a loop in the supply
    links is cut where it closes."""
    active = ordered(rows)
    by_ref = {r.ref(): r for r in active}
    cells = {r.ref(): load_cells(r, load_types, areas, by_ref, motors, drives, starters, load_factors) for r in active}
    fed: dict[str, list[LoadListRow]] = {}
    for r in active:
        if r.supplied_from in by_ref and by_ref[r.supplied_from].is_panel:
            fed.setdefault(r.supplied_from, []).append(r)
    demand = {r.ref(): load_demand(cells[r.ref()]) for r in active if not r.is_panel}
    report = LoadingReport(warn_at=warn_at)
    for r in active:
        d = demand.get(r.ref())
        if d is not None and d.left_out:
            up = by_ref.get(r.supplied_from or "")
            report.left_out.append(LeftOut(tag=r.tag(), reason=d.left_out, supplied_from=up.tag() if up else ""))

    def below(board: LoadListRow, seen: set[str]) -> list[LoadListRow]:
        out = []
        for child in fed.get(board.ref(), []):
            if child.ref() in seen:
                continue
            seen.add(child.ref())
            out.extend(below(child, seen) if child.is_panel else [child])
        return out

    def one(board: LoadListRow, depth: int) -> BoardLoading:
        c = cells[board.ref()]
        loads = [demand[x.ref()] for x in below(board, {board.ref()})]
        counted = [d for d in loads if not d.left_out]
        up = by_ref.get(board.supplied_from or "")
        b = BoardLoading(
            ref=board.ref(), tag=board.tag(), description=str(c.get("description") or ""), depth=depth,
            supplied_from="Primary Supply" if board.supplied_from == PRIMARY_SUPPLY else up.tag() if up else "",
            loads=len(counted), left_out=len(loads) - len(counted),
            connected_kw=round(sum(d.connected_kw for d in counted), 2), max_kw=round(sum(d.max_kw for d in counted), 2),
            avg_kw=round(sum(d.avg_kw for d in counted), 2), max_kva=round(sum(d.max_kva for d in counted), 2))
        volts = _number(c.get("voltage"))
        if volts is not None and volts > 0:
            b.max_amps = round(b.max_kva * 1000 / ((math.sqrt(3) if _three_phase(c.get("phases")) else 1) * volts), 1)
        rating, kind = _number(c.get("rating")), unit_kind(c.get("units"))
        if rating is None or rating <= 0:
            b.problem = "No rating: its loading can't be worked out"
        elif kind is None:
            b.problem = f"Its units ({c.get('units')}) are not kVA, kW, HP or Amps"
        elif kind == "Amps" and b.max_amps is None:
            b.problem = "Rated in Amps with no voltage"
        else:
            have = {"kVA": b.max_kva, "kW": b.max_kw, "HP": b.max_kw, "Amps": b.max_amps or 0.0}[kind]
            b.rating = rating_kw(rating, c.get("units")) if kind == "HP" else rating
            b.rating_unit = "kW" if kind == "HP" else kind
            b.loading_pct = round(have / b.rating * 100, 1)
            b.spare = round(b.rating - have, 2)
            b.over = b.loading_pct >= warn_at
        return b

    done: set[str] = set()

    def walk(board: LoadListRow, depth: int) -> None:
        if board.ref() in done:
            return
        done.add(board.ref())
        report.boards.append(one(board, depth))
        for child in fed.get(board.ref(), []):
            if child.is_panel:
                walk(child, depth + 1)

    panels = [r for r in active if r.is_panel]
    for p in panels:  # the tops first: boards fed from the primary supply, or from no board
        if p.supplied_from not in by_ref or not by_ref[p.supplied_from].is_panel:
            walk(p, 0)
    for p in panels:  # what is left is only in a loop
        walk(p, 0)
    return report


__all__ = ["DEFAULT_PF", "WARN_AT", "BoardLoading", "LeftOut", "LoadDemand", "LoadingReport", "board_loading", "load_demand"]
