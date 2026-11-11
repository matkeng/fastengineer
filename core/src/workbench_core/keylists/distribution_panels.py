# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Distribution Panels: the schedule of each distribution board (which circuit is on which
way and phase, behind which circuit breaker).

A panel is three-phase or single-phase and has an even number of ways: odd ways down the
left of the chassis, even ways down the right. On a three-phase panel each way has three
pole rows, red, white and blue (circuits QR1, QW1, QB1); on a single-phase panel a way is
one row (Q1).

The circuits come from the Project Load List: a panel is linked to a Load List row that is a
distribution panel, and every active load supplied from that row is a circuit to place. An
entry puts a load (or a spare circuit breaker, an RCD, a lighting control circuit, ...) on a
way; a three-pole entry takes the way's three rows. What the Load List doesn't hold is kept
with the entry, per pole: the circuit breaker rating, a quantity and the watts each. Left
blank, the quantity is 1 and the watts come from the load's rating. A pole row with no entry
is a spare space.

Nothing here blocks on the Load List changing underneath: a load that is deleted or moved to
another panel stays on the schedule, marked, until someone removes it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from ..generators.models import BuildResult, BuildStats, OutputRow, Scalar
from ..refdata.models import new_id
from ..refdata.validate import name_key
from .loadgen import ordered, tags_for
from .loadlist import LoadListRow
from .models import LoadType
from .panel_calc import POLES, PanelTotals, default_pole_watts, panel_totals

PanelPhaseType = Literal["three-phase", "single-phase"]
PanelViewKind = Literal["switchboard", "sld"]
Pole = Literal["R", "W", "B"]
EntryKind = Literal["load", "spare_cb", "rcd", "light_control", "other"]

#: What the Load Type column shows for an entry that is not a load (unless it is typed in).
KIND_LABELS: dict[str, str] = {"spare_cb": "DP - Spare CB", "rcd": "DP - RCD RTS", "light_control": "DP - Light Control CCT",
                               "other": ""}
SPARE_SPACE = "DP - Spare Space"
#: Circuit breaker ratings offered when typing one (any rating can be typed).
CB_RATINGS: tuple[int, ...] = (6, 10, 16, 20, 25, 32, 40, 50, 63, 80, 100, 125, 160, 200, 250)
MAX_WAYS = 96

#: The columns of a panel schedule when it is issued as a deliverable: one row per pole row.
PANEL_COLUMNS: tuple[str, ...] = ("Circuit", "Way", "Phase", "Side", "Section", "Tag", "Description", "Load Type", "Qty",
                                  "Watts (Ea.)", "Total W", "CB Rating (A)")
PANEL_DIFF_KEY = "Circuit"
PHASE_NAMES = {"R": "Red", "W": "White", "B": "Blue", "": ""}


class PoleValues(BaseModel):
    """One pole row of an entry."""
    cb_rating: float | None = None  # amps
    qty: int | None = None  # None: 1
    watts_each: float | None = None  # None: from the load's rating


class PanelEntry(BaseModel):
    id: str = Field(default_factory=new_id)
    way: int
    pole: Pole | None = None  # the row it is on; None on a single-phase panel
    poles: Literal[1, 3] = 1  # 3: the way's red, white and blue rows
    kind: EntryKind = "load"
    load_ref: str | None = None  # the Load List row (its ref()) when kind is "load"
    description: str = ""  # blank on a load: the load's description
    load_type: str = ""  # blank: the load's load type, or the kind's label
    rows: list[PoleValues] = Field(default_factory=list)  # one per pole


class PanelDivider(BaseModel):
    """A heading across the schedule above a pair of ways, e.g. "Lighting Contactor"."""
    id: str = Field(default_factory=new_id)
    before_way: int  # odd: it is drawn above ways before_way and before_way + 1
    label: str


class DistributionPanel(BaseModel):
    id: str = Field(default_factory=new_id)
    load_ref: str | None = None  # the Load List row (a distribution panel) whose loads are its circuits
    tag: str = ""  # the linked row's tag, as last seen; typed in when not linked
    title: str = ""  # blank: the linked row's description
    phase_type: PanelPhaseType = "three-phase"
    view: PanelViewKind = "switchboard"
    ways: int = 20
    voltage: float = 240  # single-phase voltage
    power_factor: float = 0.85
    isolator_rating: float = 250  # isolator and chassis rating, amps
    upstream_cb: float = 250  # upstream circuit breaker size (minimum), amps
    entries: list[PanelEntry] = Field(default_factory=list)
    dividers: list[PanelDivider] = Field(default_factory=list)


class DistributionPanelList(BaseModel):
    panels: list[DistributionPanel] = Field(default_factory=list)
    updated_at: datetime | None = None


# -- the schedule, worked out ------------------------------------------------------------------

class PoleRow(BaseModel):
    circuit: str  # QR1 / QW1 / QB1; Q1 on a single-phase panel
    way: int
    pole: str  # R / W / B; "" on a single-phase panel
    side: Literal["Left", "Right"]
    entry_id: str | None = None  # None: a spare space
    index: int = 0  # which of the entry's poles this row is
    span: int = 1  # rows the entry covers, on its first row; 0 on its other rows
    kind: str = "space"
    tag: str = ""
    description: str = ""
    load_type: str = SPARE_SPACE
    qty: int | None = None
    watts_each: float | None = None
    qty_default: bool = False  # the quantity shown was not typed in
    watts_default: bool = False
    total_w: float = 0
    cb_rating: float | None = None
    section: str = ""  # the heading it is under
    problem: str = ""


class UnplacedLoad(BaseModel):
    ref: str
    tag: str
    description: str
    load_type: str
    poles: int
    watts: float | None  # all poles together


class PanelSchedule(BaseModel):
    panel_id: str
    tag: str
    title: str
    phase_type: PanelPhaseType
    rows: list[PoleRow]  # by way, red white blue within a way
    totals: PanelTotals
    unplaced: list[UnplacedLoad]
    findings: list[str]


def circuit_name(way: int, pole: str) -> str:
    return f"Q{pole}{way}"


def panel_poles(panel: DistributionPanel) -> tuple[str, ...]:
    return POLES if panel.phase_type == "three-phase" else ("",)


def _number(v: object) -> float | None:
    if isinstance(v, bool) or v in (None, ""):
        return None
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _fed(panel: DistributionPanel, load: LoadListRow | None) -> bool:
    return load is not None and load.status == "active" and panel.load_ref is not None and load.supplied_from == panel.load_ref


def _load_facts(panel: DistributionPanel, load: LoadListRow, load_types: dict[str, LoadType]) -> dict:
    """What a load brings to the schedule: its texts, how many poles it wants, and its rating."""
    t = tags_for(load, load_types, {}, {})
    three = panel.phase_type == "three-phase" and t["phases"].casefold().startswith("ac-3-phase")
    return {"tag": t["tag"], "description": t["description"],
            "load_type": t["loadtypename"] or t.get("load_type", "") or t["equiptype"],
            "poles": 3 if three else 1, "rating": _number(load.values.get("load_rating")), "units": t["units"],
            "phases": t["phases"]}


def unplaced(panel: DistributionPanel, loads: dict[str, LoadListRow], load_types: dict[str, LoadType]) -> list[UnplacedLoad]:
    """The loads supplied from the panel that are on no way yet, in Load List order."""
    placed = {e.load_ref for e in panel.entries if e.kind == "load"}
    out = []
    for load in ordered([x for x in loads.values() if _fed(panel, x) and x.ref() not in placed]):
        f = _load_facts(panel, load, load_types)
        each = default_pole_watts(f["rating"], f["units"], f["poles"], panel.voltage, panel.power_factor)
        out.append(UnplacedLoad(ref=load.ref(), tag=f["tag"], description=f["description"], load_type=f["load_type"],
                                poles=f["poles"], watts=None if each is None else each * f["poles"]))
    return out


def _occupied(panel: DistributionPanel) -> dict[tuple[int, str], tuple[PanelEntry, int]]:
    """(way, pole) -> (entry, which of its poles). Later entries don't displace earlier ones."""
    out: dict[tuple[int, str], tuple[PanelEntry, int]] = {}
    for e in panel.entries:
        cells = [(e.way, p) for p in POLES] if e.poles == 3 else [(e.way, e.pole or "")]
        for i, cell in enumerate(cells):
            out.setdefault(cell, (e, i))
    return out


def resolve(panel: DistributionPanel, loads: dict[str, LoadListRow], load_types: dict[str, LoadType]) -> PanelSchedule:
    """The panel's schedule: every pole row with what is on it, the totals, the loads still to
    place, and what to look at. `loads`: Load List rows by ref(); `load_types` by id."""
    poles = panel_poles(panel)
    occupied = _occupied(panel)
    sections = sorted(panel.dividers, key=lambda d: d.before_way)
    linked = loads.get(panel.load_ref or "")
    findings: list[str] = []
    rows: list[PoleRow] = []
    for way in range(1, max(panel.ways, 0) + 1):
        pair = way if way % 2 else way - 1
        section = next((d.label for d in reversed(sections) if d.before_way <= pair), "")
        for pole in poles:
            row = PoleRow(circuit=circuit_name(way, pole), way=way, pole=pole, side="Left" if way % 2 else "Right",
                          section=section)
            hit = occupied.get((way, pole))
            if hit is None:
                rows.append(row)
                continue
            e, i = hit
            pv = e.rows[i] if i < len(e.rows) else PoleValues()
            row.entry_id, row.index, row.kind, row.span = e.id, i, e.kind, (e.poles if i == 0 else 0)
            row.cb_rating = pv.cb_rating
            default_w: float | None = None
            if e.kind == "load":
                load = loads.get(e.load_ref or "")
                if load is None:
                    row.problem = "Its load is no longer in the Load List"
                    row.description, row.load_type = e.description, e.load_type
                else:
                    f = _load_facts(panel, load, load_types)
                    row.tag = f["tag"]
                    row.description, row.load_type = e.description or f["description"], e.load_type or f["load_type"]
                    default_w = default_pole_watts(f["rating"], f["units"], e.poles, panel.voltage, panel.power_factor)
                    if load.status != "active":
                        row.problem = "Its load is deleted in the Load List"
                    elif not _fed(panel, load):
                        row.problem = "Its load is no longer supplied from this panel"
                    elif "1-phase-ll" in f["phases"].casefold():
                        row.problem = "A line-to-line load: it is counted on one phase only"
            else:
                row.description, row.load_type = e.description, e.load_type or KIND_LABELS.get(e.kind, "")
            row.watts_each = pv.watts_each if pv.watts_each is not None else default_w
            row.watts_default = pv.watts_each is None and default_w is not None
            if row.watts_each is not None:
                row.qty = pv.qty if pv.qty is not None else 1
                row.qty_default = pv.qty is None
                row.total_w = row.qty * row.watts_each
            else:
                row.qty = pv.qty
            if row.problem and i == 0:
                findings.append(f"{row.circuit} {row.tag or row.description or row.load_type}: {row.problem.lower()}.")
            rows.append(row)

    totals = panel_totals(((r.pole, r.total_w) for r in rows), three_phase=panel.phase_type == "three-phase",
                          voltage=panel.voltage, power_factor=panel.power_factor, isolator_rating=panel.isolator_rating)
    waiting = unplaced(panel, loads, load_types)
    if panel.load_ref is None:
        findings.insert(0, "Not linked to a distribution panel of the Load List: its circuits are typed in.")
    elif linked is None or linked.status != "active" or not linked.is_panel:
        findings.insert(0, "The Load List row it is linked to is deleted or is no longer a distribution panel.")
    if waiting:
        findings.append(f"{len(waiting)} load(s) supplied from this panel are not on a way yet: "
                        + ", ".join(u.tag for u in waiting[:12]) + (f" and {len(waiting) - 12} more" if len(waiting) > 12 else "")
                        + ".")
    if panel.isolator_rating > 0 and totals.max_amps > panel.isolator_rating:
        findings.append(f"Maximum Amp ({totals.max_amps:.1f} A) is more than the isolator and chassis rating "
                        f"({panel.isolator_rating:g} A).")
    big = [r.circuit for r in rows if r.cb_rating is not None and panel.isolator_rating > 0 and r.cb_rating > panel.isolator_rating]
    if big:
        findings.append(f"Circuit breaker(s) rated above the isolator and chassis: {', '.join(big[:12])}.")
    if panel.upstream_cb > panel.isolator_rating > 0:
        findings.append(f"The upstream CB ({panel.upstream_cb:g} A) is larger than the isolator and chassis rating "
                        f"({panel.isolator_rating:g} A).")
    title = panel.title.strip() or (str(linked.values.get("desc") or "").strip() if linked else "")
    return PanelSchedule(panel_id=panel.id, tag=panel.tag, title=title, phase_type=panel.phase_type, rows=rows, totals=totals,
                         unplaced=waiting, findings=findings)


def auto_place(panel: DistributionPanel, loads: dict[str, LoadListRow], load_types: dict[str, LoadType]) -> DistributionPanel:
    """Put every load not yet on a way on the first free one, in way order: a three-pole load
    takes the next way whose three rows are free; a single-pole load the next free row. A load
    that doesn't fit is left to place."""
    panel = panel.model_copy(deep=True)
    poles = panel_poles(panel)
    taken = set(_occupied(panel))
    for u in unplaced(panel, loads, load_types):
        for way in range(1, panel.ways + 1):
            if u.poles == 3:
                free = [""] if not any((way, p) in taken for p in POLES) else []
                cells = [(way, p) for p in POLES]
            else:
                free = [p for p in poles if (way, p) not in taken][:1]
                cells = [(way, p) for p in free]
            if free:
                panel.entries.append(PanelEntry(way=way, pole=(cells[0][1] or None) if u.poles == 1 else "R", poles=u.poles,  # type: ignore[arg-type]
                                                kind="load", load_ref=u.ref, rows=[PoleValues() for _ in range(u.poles)]))
                taken.update(cells)
                break
    return panel


# -- checks ------------------------------------------------------------------------------------

def check_panels(doc: DistributionPanelList, loads: dict[str, LoadListRow]) -> tuple[DistributionPanelList, dict[str, str]]:
    """The list tidied (texts trimmed, a linked panel's tag refreshed from its Load List row)
    and its errors, field -> message, which block a save. Fields are `<id>.<field>`, the id
    being a panel's, an entry's or a divider's."""
    doc = doc.model_copy(deep=True)
    errors: dict[str, str] = {}
    tags: set[str] = set()
    links: set[str] = set()
    for p in doc.panels:
        p.title = p.title.strip()
        linked = loads.get(p.load_ref or "")
        if p.load_ref is not None:
            if linked is not None and linked.status == "active" and linked.is_panel:
                p.tag = linked.tag()
            elif linked is None and not p.tag.strip():
                errors[f"{p.id}.load_ref"] = "That Load List row no longer exists"
            if p.load_ref in links:
                errors[f"{p.id}.load_ref"] = "Another panel is linked to this Load List row"
            links.add(p.load_ref)
        p.tag = p.tag.strip()
        if not p.tag:
            errors[f"{p.id}.tag"] = "Tag is required"
        elif name_key(p.tag) in tags:
            errors[f"{p.id}.tag"] = f"Tag '{p.tag}' is used twice"
        tags.add(name_key(p.tag))
        if p.ways < 2 or p.ways > MAX_WAYS or p.ways % 2:
            errors[f"{p.id}.ways"] = f"Ways is an even number from 2 to {MAX_WAYS}"
        if p.voltage <= 0:
            errors[f"{p.id}.voltage"] = "Voltage must be more than 0"
        if not 0 < p.power_factor <= 1:
            errors[f"{p.id}.power_factor"] = "Power factor is more than 0, up to 1"
        if p.isolator_rating <= 0:
            errors[f"{p.id}.isolator_rating"] = "The rating must be more than 0"
        if p.upstream_cb <= 0:
            errors[f"{p.id}.upstream_cb"] = "The size must be more than 0"
        three = p.phase_type == "three-phase"
        taken: dict[tuple[int, str], str] = {}
        placed: set[str] = set()
        for e in p.entries:
            e.description, e.load_type = e.description.strip(), e.load_type.strip()
            if not 1 <= e.way <= p.ways:
                errors[f"{e.id}.way"] = f"The panel has ways 1 to {p.ways}"
            if three and e.pole is None:
                errors[f"{e.id}.pole"] = "Choose red, white or blue"
            elif not three and e.pole is not None:
                errors[f"{e.id}.pole"] = "A single-phase panel has no red, white and blue rows"
            if e.poles == 3 and not three:
                errors[f"{e.id}.poles"] = "A single-phase panel has single-pole circuits only"
            elif e.poles == 3 and e.pole != "R":
                errors[f"{e.id}.pole"] = "A three-pole circuit starts on the red row"
            if len(e.rows) != e.poles:
                errors[f"{e.id}.rows"] = f"A {e.poles}-pole circuit has {e.poles} row(s) of values"
            if any((v.qty is not None and v.qty < 0) or (v.watts_each is not None and v.watts_each < 0)
                   or (v.cb_rating is not None and v.cb_rating < 0) for v in e.rows):
                errors[f"{e.id}.rows"] = "Quantity, watts and CB rating can't be negative"
            if e.kind == "load":
                if not e.load_ref:
                    errors[f"{e.id}.load_ref"] = "Choose a load"
                elif e.load_ref in placed:
                    errors[f"{e.id}.load_ref"] = "This load is on the panel twice"
                placed.add(e.load_ref or "")
            else:
                e.load_ref = None
            for cell in ([(e.way, x) for x in POLES] if e.poles == 3 else [(e.way, e.pole or "")]):
                if cell in taken and taken[cell] != e.id:
                    errors[f"{e.id}.way"] = f"{circuit_name(*cell)} already has a circuit"
                taken.setdefault(cell, e.id)
        before: set[int] = set()
        for d in p.dividers:
            d.label = d.label.strip()
            if not d.label:
                errors[f"{d.id}.label"] = "A heading needs its text"
            if not 1 <= d.before_way <= p.ways or d.before_way % 2 == 0:
                errors[f"{d.id}.before_way"] = "A heading goes above an odd way of the panel"
            elif d.before_way in before:
                errors[f"{d.id}.before_way"] = "There is already a heading there"
            before.add(d.before_way)
    return doc, errors


# -- as a deliverable --------------------------------------------------------------------------

def _num(v: float | None) -> Scalar:
    if v is None:
        return None
    v = round(v, 2)
    return int(v) if v == int(v) else v


def flatten(schedule: PanelSchedule) -> BuildResult:
    """The schedule as flat rows, one per pole row (spare spaces too), for a deliverable. A
    three-pole circuit is three rows with the same tag, description and load type."""
    by_entry = {r.entry_id: r for r in schedule.rows if r.entry_id is not None and r.span}
    rows = []
    for r in schedule.rows:
        first = by_entry.get(r.entry_id, r)
        cells: list[Scalar] = [r.circuit, r.way, PHASE_NAMES[r.pole], r.side, r.section, first.tag, first.description,
                               first.load_type, r.qty, _num(r.watts_each), _num(r.total_w) if r.watts_each is not None else None,
                               _num(r.cb_rating)]
        rows.append(OutputRow(cells=["" if c is None else c for c in cells], run_row_id=f"{schedule.panel_id}:{r.circuit}"))
    return BuildResult(header=list(PANEL_COLUMNS), rows=rows, stats=BuildStats(rows_written=len(rows), output_rows=len(rows)),
                       engine_version="distribution panels")


def summary_lines(panel: DistributionPanel, schedule: PanelSchedule) -> list[tuple[str, Scalar]]:
    """The panel's header block, as label and value, for a deliverable and its export."""
    t = schedule.totals
    three = panel.phase_type == "three-phase"
    out: list[tuple[str, Scalar]] = [
        ("Panel", schedule.tag), ("Title", schedule.title), ("Phase type", "Three-phase" if three else "Single-phase"),
        ("Single Phase Voltage", _num(panel.voltage)), ("Power Factor", _num(panel.power_factor)),
        ("Isolator & Chassis Rating (Amps)", _num(panel.isolator_rating)), ("Upstream CB Size (Min)", _num(panel.upstream_cb)),
        ("Maximum Amp", _num(t.max_amps)), ("3PH kW" if three else "Total kW", _num(t.total_kw)),
        ("Remaining Capacity (Amps)", _num(t.remaining_amps)), ("Remaining Capacity %", _num(t.remaining_pct)),
        ("Maximum kVA Rating", _num(t.max_kva))]
    out += [(f"kVA {PHASE_NAMES[p]}".strip(), _num(k)) for p, k in zip(t.phases, t.phase_kva)]
    return out
