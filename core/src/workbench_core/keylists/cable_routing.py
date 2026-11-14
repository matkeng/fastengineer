# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Cable Routing: a node map of the plant's cable ladder routes, and what follows from it.

The map is a symbolic diagram, not to scale. **Equipment** is placed on it as rectangles
(by tag: the tags the Project Master Cable Schedule's From and To name). **Nodes** (N001 to
N999) are the points where ladders meet, and **segments** (S-001...) are the ladder runs
between two nodes, or between a node and a piece of equipment. A segment's length is typed
in; its place on the drawing says nothing about it. Routes may form loops.

From the map and the cable schedule:

- every cable is **routed** from its From to its To equipment along the shortest way (by
  length), or along the way its override names (through given nodes or segments, avoiding
  others), and its length is the sum of the segments' lengths plus an allowance;
- every segment gets, for each **service** (HV, LV power, control...) whose cables use it,
  the ladder width those cables need by the project's loading rules, and their mass per metre.
"""

from __future__ import annotations

import heapq
import math
import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from ..generators.models import BuildResult
from ..refdata.models import new_id
from ..refdata.validate import name_key
from .cable_types import CableType
from .loadgen import match_cable

MAX_NODES = 999
#: Three single core cables laid as a trefoil take the width of the circle around them: 2.15 diameters.
TREFOIL_FACTOR = 2.15
NODE_TAG = re.compile(r"^N(\d{3})$")
SEGMENT_TAG = re.compile(r"^S-(\d{3,})$")
_SINGLE_CORE = re.compile(r"^1\s*(c|core)?$")


def node_tag(n: int) -> str:
    return f"N{n:03d}"


def segment_tag(n: int) -> str:
    return f"S-{n:03d}"


# -- the document ----------------------------------------------------------------------------

class Placement(BaseModel):
    """A piece of equipment on the map. `tag` is what cables' From and To are matched on;
    `source` is the Project Master Equipment List row it was dragged from (so a renamed tag
    follows), None for one typed in (a junction box, "Primary Supply")."""
    id: str = Field(default_factory=new_id)
    tag: str = ""
    description: str = ""
    source: str | None = None
    x: float = 0
    y: float = 0
    w: float = 120
    h: float = 60


class RouteNode(BaseModel):
    id: str = Field(default_factory=new_id)
    tag: str = ""  # N001
    x: float = 0
    y: float = 0


class End(BaseModel):
    kind: Literal["node", "equipment"] = "node"
    id: str = ""


class LadderOverride(BaseModel):
    """What is installed on a segment for one service, where it is not left to the rules."""
    width_mm: int | None = None
    max_kg_per_m: float | None = None


class Segment(BaseModel):
    id: str = Field(default_factory=new_id)
    tag: str = ""  # S-001
    a: End = Field(default_factory=End)
    b: End = Field(default_factory=End)
    bends: list[tuple[float, float]] = Field(default_factory=list)  # the corners of a polyline, from a to b
    length_m: float | None = None
    ladders: dict[str, LadderOverride] = Field(default_factory=dict)  # service id -> what is installed


class Service(BaseModel):
    """A group of cables that share a ladder, and the rules its ladders are sized by."""
    id: str = Field(default_factory=new_id)
    name: str = ""
    colour: str = "#2563eb"
    spacing_factor: float = 0  # the gap left beside each cable, in cable diameters
    max_layers: int = 1
    spare_pct: float = 25  # width kept free for future cables
    widths_mm: list[int] = Field(default_factory=lambda: list(DEFAULT_WIDTHS))
    max_kg_per_m: float | None = 50  # what one ladder carries


RuleField = Literal["application", "type", "voltage", "code", "description"]


class ServiceRule(BaseModel):
    """Cables whose cable type's `field` contains `contains` (ignoring case) belong to the service. The first rule that fits wins."""
    id: str = Field(default_factory=new_id)
    field: RuleField = "type"
    contains: str = ""
    service_id: str = ""


class Allowance(BaseModel):
    """What is added to a route's length, and whether the Project Master Cable Schedule shows the result."""
    apply_to_master: bool = False
    tail_from_m: float = 0
    tail_to_m: float = 0
    contingency_pct: float = 0
    round_up_to_m: float = 1  # 0: not rounded
    route_column: Literal["never", "when blank", "always"] = "when blank"


class CableOverride(BaseModel):
    """A cable's own route: through these nodes and segments (ids, in order), and never along the avoided segments."""
    via: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)


DEFAULT_WIDTHS = (150, 300, 450, 600, 750, 900)


def default_services() -> list[Service]:
    return [Service(id="hv", name="HV", colour="#dc2626", spacing_factor=1),
            Service(id="lv", name="LV Power", colour="#2563eb"),
            Service(id="control", name="Control", colour="#16a34a", max_layers=2),
            Service(id="instrument", name="Instrumentation", colour="#9333ea", max_layers=2),
            Service(id="comms", name="Comms", colour="#0891b2", max_layers=2)]


def default_rules() -> list[ServiceRule]:
    rules = [("type", "Instrument", "instrument"), ("description", "Instrolex", "instrument"), ("type", "Control", "control"),
             ("application", "Network", "comms"), ("type", "Fibre", "comms"), ("type", "Ethernet", "comms")]
    rules += [("voltage", f"/{kv}kV", "hv") for kv in ("3.3", "6.6", "11", "22", "33")]
    return [ServiceRule(id=f"r{i}", field=f, contains=c, service_id=s) for i, (f, c, s) in enumerate(rules, start=1)]  # type: ignore[arg-type]


class CableRouting(BaseModel):
    placements: list[Placement] = Field(default_factory=list)
    nodes: list[RouteNode] = Field(default_factory=list)
    segments: list[Segment] = Field(default_factory=list)
    services: list[Service] = Field(default_factory=default_services)
    service_rules: list[ServiceRule] = Field(default_factory=default_rules)
    default_service_id: str = "lv"
    allowance: Allowance = Field(default_factory=Allowance)
    overrides: dict[str, CableOverride] = Field(default_factory=dict)  # name_key(Cable Number) -> its route
    next_node: int = 1  # numbers are given out in order and not reused (until they run out)
    next_segment: int = 1
    grid: float = 20
    updated_at: datetime | None = None


def _free_number(used: set[int], start: int, limit: int | None) -> int | None:
    """The next number from `start` not in use; past `limit`, the lowest free one. None when all are taken."""
    n = max(start, 1)
    while n in used:
        n += 1
    if limit is None or n <= limit:
        return n
    return next((i for i in range(1, limit + 1) if i not in used), None)


def _numbers(tags: list[str], pattern: re.Pattern[str]) -> set[int]:
    return {int(m.group(1)) for m in (pattern.match(t) for t in tags) if m}


def add_node(doc: CableRouting, x: float, y: float) -> RouteNode:
    """A new node with the next tag, added to `doc`. ValueError when all 999 are in use."""
    n = _free_number(_numbers([d.tag for d in doc.nodes], NODE_TAG), doc.next_node, MAX_NODES)
    if n is None or len(doc.nodes) >= MAX_NODES:
        raise ValueError(f"A node map has at most {MAX_NODES} nodes.")
    node = RouteNode(tag=node_tag(n), x=x, y=y)
    doc.nodes.append(node)
    doc.next_node = n + 1
    return node


def add_segment(doc: CableRouting, a: End, b: End, length_m: float | None = None) -> Segment:
    """A new segment with the next tag, added to `doc`."""
    n = _free_number(_numbers([s.tag for s in doc.segments], SEGMENT_TAG), doc.next_segment, None)
    seg = Segment(tag=segment_tag(n or 1), a=a, b=b, length_m=length_m)
    doc.segments.append(seg)
    doc.next_segment = (n or 1) + 1
    return seg


def check_routing(doc: CableRouting) -> tuple[CableRouting, dict[str, str], list[str]]:
    """The map tidied (tags trimmed, the counters past the tags in use), its errors (field ->
    message; they block a save) and its warnings. Fields are `<id>.<field>`."""
    doc = doc.model_copy(deep=True)
    errors: dict[str, str] = {}
    warnings: list[str] = []
    ids: set[str] = set()

    def unique(item_id: str) -> None:
        if not item_id or item_id in ids:
            errors[f"{item_id}.id"] = "Two things on the map have the same id"
        ids.add(item_id)

    service_ids = {s.id for s in doc.services}
    names: set[str] = set()
    for s in doc.services:
        unique(s.id)
        s.name = s.name.strip()
        if not s.name:
            errors[f"{s.id}.name"] = "Name is required"
        elif name_key(s.name) in names:
            errors[f"{s.id}.name"] = f"Service '{s.name}' is there twice"
        names.add(name_key(s.name))
        if s.spacing_factor < 0:
            errors[f"{s.id}.spacing_factor"] = "Spacing is 0 or more"
        if s.max_layers < 1:
            errors[f"{s.id}.max_layers"] = "Layers is 1 or more"
        if s.spare_pct < 0:
            errors[f"{s.id}.spare_pct"] = "Spare is 0 or more"
        s.widths_mm = sorted({w for w in s.widths_mm if w > 0})
        if not s.widths_mm:
            errors[f"{s.id}.widths_mm"] = "Give at least one ladder width"
        if s.max_kg_per_m is not None and s.max_kg_per_m <= 0:
            errors[f"{s.id}.max_kg_per_m"] = "The load limit is more than 0, or blank"
    if not doc.services:
        errors["services"] = "There must be at least one service"
    elif doc.default_service_id not in service_ids:
        doc.default_service_id = doc.services[0].id
    for r in doc.service_rules:
        r.contains = r.contains.strip()
        if r.service_id not in service_ids:
            errors[f"{r.id}.service_id"] = "That service no longer exists"
        if not r.contains:
            errors[f"{r.id}.contains"] = "Say what the text contains"

    tags: dict[str, int] = {}
    for p in doc.placements:
        unique(p.id)
        p.tag, p.description = p.tag.strip(), p.description.strip()
        if not p.tag:
            errors[f"{p.id}.tag"] = "Tag is required"
        tags[name_key(p.tag)] = tags.get(name_key(p.tag), 0) + 1
        if p.w <= 0 or p.h <= 0:
            errors[f"{p.id}.w"] = "A rectangle has a width and a height"
    twice = sorted(p.tag for p in doc.placements if p.tag and tags[name_key(p.tag)] > 1)
    if twice:
        warnings.append(f"Placed more than once (cables go to the first): {', '.join(sorted(set(twice))[:10])}.")

    node_tags: set[str] = set()
    for n in doc.nodes:
        unique(n.id)
        n.tag = n.tag.strip().upper()
        if not NODE_TAG.match(n.tag) or n.tag == "N000":
            errors[f"{n.id}.tag"] = "A node's tag is N001 to N999"
        elif n.tag in node_tags:
            errors[f"{n.id}.tag"] = f"Node {n.tag} is there twice"
        node_tags.add(n.tag)
    if len(doc.nodes) > MAX_NODES:
        errors["nodes"] = f"A node map has at most {MAX_NODES} nodes ({len(doc.nodes)} drawn)"

    ends = {"node": {n.id for n in doc.nodes}, "equipment": {p.id for p in doc.placements}}
    seg_tags: set[str] = set()
    unmeasured = []
    for s in doc.segments:
        unique(s.id)
        s.tag = s.tag.strip().upper()
        if not SEGMENT_TAG.match(s.tag):
            errors[f"{s.id}.tag"] = "A segment's tag is S-001, S-002..."
        elif s.tag in seg_tags:
            errors[f"{s.id}.tag"] = f"Segment {s.tag} is there twice"
        seg_tags.add(s.tag)
        for side, end in (("a", s.a), ("b", s.b)):
            if end.id not in ends[end.kind]:
                errors[f"{s.id}.{side}"] = f"{s.tag} ends on something that is no longer on the map"
        if (s.a.kind, s.a.id) == (s.b.kind, s.b.id):
            errors[f"{s.id}.b"] = f"{s.tag} starts and ends on the same thing"
        if s.length_m is not None and s.length_m < 0:
            errors[f"{s.id}.length_m"] = "Length is 0 or more"
        elif s.length_m is None:
            unmeasured.append(s.tag)
        s.ladders = {k: v for k, v in s.ladders.items() if k in service_ids and (v.width_mm or v.max_kg_per_m)}
        for k, v in s.ladders.items():
            if (v.width_mm is not None and v.width_mm <= 0) or (v.max_kg_per_m is not None and v.max_kg_per_m <= 0):
                errors[f"{s.id}.ladders.{k}"] = "A ladder's width and load limit are more than 0, or blank"
    if unmeasured:
        warnings.append(f"{len(unmeasured)} segment(s) have no length yet: {', '.join(sorted(unmeasured)[:10])}"
                        + ("..." if len(unmeasured) > 10 else "") + ".")

    a = doc.allowance
    for field in ("tail_from_m", "tail_to_m", "contingency_pct", "round_up_to_m"):
        if getattr(a, field) < 0:
            errors[f"allowance.{field}"] = "0 or more"
    known = ends["node"] | {s.id for s in doc.segments}
    doc.overrides = {name_key(k): v for k, v in doc.overrides.items() if k.strip() and (v.via or v.avoid)}
    for k, v in doc.overrides.items():
        if any(i not in known for i in [*v.via, *v.avoid]):
            v.via, v.avoid = [i for i in v.via if i in known], [i for i in v.avoid if i in known]
            warnings.append(f"The route given for cable {k.upper()} named nodes or segments that are gone; they were dropped.")
    doc.next_node = max([doc.next_node, 1, *(n + 1 for n in _numbers(list(node_tags), NODE_TAG))])
    doc.next_segment = max([doc.next_segment, 1, *(n + 1 for n in _numbers(list(seg_tags), SEGMENT_TAG))])
    return doc, errors, warnings


def renumber(doc: CableRouting) -> CableRouting:
    """The nodes and segments numbered again from 1, in the order they are in."""
    doc = doc.model_copy(deep=True)
    for i, n in enumerate(doc.nodes, start=1):
        n.tag = node_tag(i)
    for i, s in enumerate(doc.segments, start=1):
        s.tag = segment_tag(i)
    doc.next_node, doc.next_segment = len(doc.nodes) + 1, len(doc.segments) + 1
    return doc


class EquipmentChoice(BaseModel):
    """A row of the Project Master Equipment List, to place on the map."""
    tag: str
    description: str = ""
    source: str = ""  # "<run_row_id>#<template_seq>"
    placed: bool = False


def equipment_of(result: BuildResult) -> list[EquipmentChoice]:
    """The equipment of a Project Master Equipment List: one per tag, in the list's order."""
    if "Tag" not in result.header:
        return []
    t = result.header.index("Tag")
    d = result.header.index("Description") if "Description" in result.header else None
    out: dict[str, EquipmentChoice] = {}
    for r in result.rows:
        tag = str(r.cells[t] if r.cells[t] is not None else "").strip()
        if tag and name_key(tag) not in out:
            out[name_key(tag)] = EquipmentChoice(tag=tag, description=str(r.cells[d] or "").strip() if d is not None else "",
                                                source=f"{r.run_row_id}#{r.template_seq}")
    return list(out.values())


def follow_equipment(doc: CableRouting, equipment: list[EquipmentChoice]) -> CableRouting:
    """`doc` with each placed equipment's tag and description as its Equipment List row has them now."""
    by_source = {e.source: e for e in equipment}
    by_tag = {name_key(e.tag): e for e in equipment}
    doc = doc.model_copy(deep=True)
    for p in doc.placements:
        e = by_source.get(p.source or "") or (by_tag.get(name_key(p.tag)) if p.source else None)
        if e is not None:
            p.tag, p.description, p.source = e.tag, e.description, e.source
    return doc


# -- the cables ------------------------------------------------------------------------------

class CableIn(BaseModel):
    """A cable of the schedule, with what routing and ladder sizing need of it."""
    row: int  # its place in the schedule
    key: str  # name_key(number): what an override is kept under
    number: str
    from_tag: str
    to_tag: str
    cable_code: str = ""
    type_cell: str = ""
    cores: str = ""
    size: str = ""
    cable_type_id: str | None = None
    service_id: str = ""
    od_mm: float | None = None
    mass_kg_per_m: float | None = None
    single_core: bool = False


CABLE_COLUMNS = ("Cable Number", "From", "To")
LENGTH, ROUTE = "Length (m)", "Route"


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def service_of(doc: CableRouting, cable: CableType | None, type_cell: str = "") -> str:
    """The service a cable belongs to: the first rule its cable type fits, else the default service."""
    subject = cable or CableType(code="", type=type_cell)
    for rule in doc.service_rules:
        if rule.contains and rule.contains.casefold() in str(getattr(subject, rule.field, "")).casefold():
            return rule.service_id
    return doc.default_service_id


def cables_of(result: BuildResult, cable_types: list[CableType], doc: CableRouting) -> tuple[list[CableIn], list[str]]:
    """The cables of a Project Master Cable Schedule, each with its cable type's diameter and
    mass and its service; and what is wrong with the schedule for routing."""
    missing = [c for c in CABLE_COLUMNS if c not in result.header]
    if missing:
        return [], [f"The Project Master Cable Schedule has no {' or '.join(missing)} column, so its cables cannot be routed."]
    col = {name: result.header.index(name) for name in ("Cable Number", "From", "To", "Cable Type", "Cable Code", "Cores", "Size")
           if name in result.header}
    by_code = {name_key(c.code): c for c in cable_types}
    out: list[CableIn] = []
    for i, r in enumerate(result.rows):
        def cell(name: str) -> str:
            return _text(r.cells[col[name]]) if name in col else ""
        number, code = cell("Cable Number"), cell("Cable Code")
        kind = by_code.get(name_key(code)) if code else None
        if kind is None and (cell("Cable Type") or cell("Cores")) and cell("Size"):
            kind = match_cable(cable_types, cell("Cable Type"), cell("Cores"), cell("Size"))[0]
        cores = cell("Cores") or (kind.cores if kind else "")
        out.append(CableIn(row=i, key=name_key(number), number=number, from_tag=cell("From"), to_tag=cell("To"), cable_code=code,
                           type_cell=cell("Cable Type"), cores=cores, size=cell("Size"), cable_type_id=kind.id if kind else None,
                           service_id=service_of(doc, kind, cell("Cable Type")),
                           od_mm=kind.overall_diameter_mm if kind else None, mass_kg_per_m=kind.mass_kg_per_m if kind else None,
                           single_core=bool(_SINGLE_CORE.match(cores.strip().casefold()))))
    return out, []


# -- routing ---------------------------------------------------------------------------------

Status = Literal["ok", "from not placed", "to not placed", "same equipment", "no route", "missing lengths"]


class CableRoute(BaseModel):
    row: int
    key: str
    number: str
    from_tag: str
    to_tag: str
    cable_code: str = ""
    service_id: str = ""
    od_mm: float | None = None
    mass_kg_per_m: float | None = None
    status: Status = "ok"
    overridden: bool = False
    segments: list[str] = Field(default_factory=list)  # segment ids, From to To
    nodes: list[str] = Field(default_factory=list)  # the tags of the nodes passed
    route: str = ""  # "N001-N004-N007"
    route_m: float | None = None  # the segments' lengths added up
    length_m: float | None = None  # with the allowance: what the cable schedule shows


Cost = tuple[int, float]  # (segments with no length, metres): a way over measured segments always wins


class _Graph:
    def __init__(self, doc: CableRouting):
        self.segments = {s.id: s for s in doc.segments}
        self.equipment = {p.id for p in doc.placements}
        self.adjacent: dict[str, list[tuple[str, str]]] = {}  # vertex -> [(segment id, other vertex)]
        for s in sorted(doc.segments, key=lambda s: s.tag):
            self.adjacent.setdefault(s.a.id, []).append((s.id, s.b.id))
            self.adjacent.setdefault(s.b.id, []).append((s.id, s.a.id))
        self._cache: dict[tuple, tuple[dict[str, Cost], dict[str, tuple[str, str]]]] = {}

    def cost(self, seg_id: str) -> Cost:
        length = self.segments[seg_id].length_m
        return (1, 0.0) if length is None else (0, length)

    def _from(self, src: str, avoid: frozenset[str]):
        """Dijkstra from `src`: (cost to each vertex, how each was reached: (previous vertex, segment id)).
        Equipment is where a route ends, never a way through."""
        key = (src, avoid)
        if key in self._cache:
            return self._cache[key]
        dist: dict[str, Cost] = {src: (0, 0.0)}
        prev: dict[str, tuple[str, str]] = {}
        heap: list[tuple[Cost, int, str]] = [((0, 0.0), 0, src)]
        count = 0
        done: set[str] = set()
        while heap:
            d, _, v = heapq.heappop(heap)
            if v in done:
                continue
            done.add(v)
            if v in self.equipment and v != src:
                continue
            for seg_id, other in self.adjacent.get(v, []):
                if seg_id in avoid:
                    continue
                c = self.cost(seg_id)
                nd = (d[0] + c[0], d[1] + c[1])
                if other not in dist or nd < dist[other]:
                    dist[other], prev[other] = nd, (v, seg_id)
                    count += 1
                    heapq.heappush(heap, (nd, count, other))
        self._cache[key] = (dist, prev)
        return dist, prev

    def path(self, src: str, dst: str, avoid: frozenset[str]) -> tuple[Cost, list[str]] | None:
        """The shortest way from `src` to `dst`: (cost, segment ids), or None."""
        if src == dst:
            return (0, 0.0), []
        dist, prev = self._from(src, avoid)
        if dst not in dist:
            return None
        segs: list[str] = []
        v = dst
        while v != src:
            v, seg_id = prev[v]
            segs.append(seg_id)
        return dist[dst], segs[::-1]

    def route(self, src: str, dst: str, override: CableOverride | None) -> tuple[Cost, list[str]] | None:
        """The shortest way from `src` to `dst` through the override's nodes and segments in
        order, never along a segment twice."""
        avoid = frozenset(override.avoid) if override else frozenset()
        # each stop: the ways to pass it, as (enter at, leave at, segments inside)
        stops: list[list[tuple[str, str, list[str]]]] = []
        for via in (override.via if override else []):
            seg = self.segments.get(via)
            stops.append([(via, via, [])] if seg is None else [(seg.a.id, seg.b.id, [seg.id]), (seg.b.id, seg.a.id, [seg.id])])
        stops.append([(dst, dst, [])])
        states: list[tuple[str, Cost, list[str]]] = [(src, (0, 0.0), [])]  # (at, cost so far, segments so far)
        for stop in stops:
            reached: list[tuple[str, Cost, list[str]]] = []
            for enter, leave, inner in stop:
                best: tuple[Cost, list[str]] | None = None
                for at, so_far, segs in states:
                    if any(s in segs for s in inner):
                        continue
                    leg = self.path(at, enter, avoid | frozenset(segs) | frozenset(inner))
                    if leg is None:
                        continue
                    total = (so_far[0] + leg[0][0], so_far[1] + leg[0][1])
                    if best is None or total < best[0]:
                        best = (total, segs + leg[1])
                if best is not None:
                    inside = [self.cost(s) for s in inner]
                    cost = (best[0][0] + sum(c[0] for c in inside), best[0][1] + sum(c[1] for c in inside))
                    reached.append((leave, cost, best[1] + inner))
            if not reached:
                return None
            states = reached
        return min(((s[1], s[2]) for s in states), key=lambda x: x[0])


def final_length(route_m: float, a: Allowance) -> float:
    """A route's length with the tails and contingency added, rounded up."""
    length = (route_m + a.tail_from_m + a.tail_to_m) * (1 + a.contingency_pct / 100)
    if a.round_up_to_m > 0:
        return round(math.ceil(round(length / a.round_up_to_m, 6)) * a.round_up_to_m, 3)
    return round(length, 1)


def route_cables(doc: CableRouting, cables: list[CableIn]) -> list[CableRoute]:
    """Every cable's route over the map (see the module's words on routing)."""
    graph = _Graph(doc)
    placed: dict[str, str] = {}
    for p in doc.placements:
        placed.setdefault(name_key(p.tag), p.id)
    node_tags = {n.id: n.tag for n in doc.nodes}
    seg_tags = {s.id: s.tag for s in doc.segments}
    out: list[CableRoute] = []
    for c in cables:
        r = CableRoute(row=c.row, key=c.key, number=c.number, from_tag=c.from_tag, to_tag=c.to_tag, cable_code=c.cable_code,
                       service_id=c.service_id, od_mm=c.od_mm, mass_kg_per_m=c.mass_kg_per_m)
        out.append(r)
        src, dst = placed.get(name_key(c.from_tag)), placed.get(name_key(c.to_tag))
        override = doc.overrides.get(c.key) if c.key else None
        r.overridden = override is not None
        if src is None or dst is None:
            r.status = "from not placed" if src is None else "to not placed"
            continue
        if src == dst:
            r.status = "same equipment"
            continue
        found = graph.route(src, dst, override)
        if found is None:
            r.status = "no route"
            continue
        (unmeasured, length), r.segments = found
        if unmeasured:
            r.status = "missing lengths"
        at = src
        for seg_id in r.segments:
            s = graph.segments[seg_id]
            at = s.b.id if s.a.id == at else s.a.id
            if at in node_tags:
                r.nodes.append(node_tags[at])
        r.route = "-".join(r.nodes) if r.nodes else "-".join(seg_tags[s] for s in r.segments)
        if r.status == "ok":
            r.route_m = round(length, 3)
            r.length_m = final_length(length, doc.allowance)
    return out


# -- ladders ---------------------------------------------------------------------------------

class ServiceLoad(BaseModel):
    """One service's cables on one segment, and the ladder they need."""
    service_id: str
    cables: int = 0
    trefoils: int = 0  # groups of three single core cables counted as one trefoil
    sum_od_mm: float = 0  # the width the cables take side by side, trefoils as one
    required_mm: float = 0  # with the spacing, the layers and the spare
    width_mm: int | None = None  # the ladder: the standard width at or above that (or the one installed)
    ladders: int = 1  # how many ladders of that width
    fill_pct: float | None = None  # the cables' width (without the spare) against the ladders'
    kg_per_m: float = 0
    max_kg_per_m: float | None = None  # what the ladders carry
    missing_od: list[str] = Field(default_factory=list)  # cable numbers left out of the width
    missing_mass: list[str] = Field(default_factory=list)  # cable numbers left out of the mass
    flags: list[str] = Field(default_factory=list)


class SegmentLoad(BaseModel):
    id: str
    tag: str
    length_m: float | None = None
    cables: list[int] = Field(default_factory=list)  # schedule rows of the cables on it
    services: list[ServiceLoad] = Field(default_factory=list)
    width_mm: int = 0  # the services' ladders side by side
    kg_per_m: float = 0
    worst: Literal["", "ok", "full", "over"] = ""  # no cables, fine, a ladder too narrow for the spare, a ladder overloaded


def _ladder(service: Service, override: LadderOverride | None, cables: list[CableIn]) -> ServiceLoad:
    load = ServiceLoad(service_id=service.id, cables=len(cables))
    groups: dict[tuple, list[CableIn]] = {}
    widths: list[float] = []
    for c in cables:
        if c.od_mm is None:
            load.missing_od.append(c.number)
        elif c.single_core:
            groups.setdefault((name_key(c.from_tag), name_key(c.to_tag), c.cable_type_id or c.cable_code, c.od_mm), []).append(c)
        else:
            widths.append(c.od_mm)
        if c.mass_kg_per_m is None:
            load.missing_mass.append(c.number)
        else:
            load.kg_per_m += c.mass_kg_per_m
    for (_, _, _, od), group in groups.items():
        load.trefoils += len(group) // 3
        widths += [od * TREFOIL_FACTOR] * (len(group) // 3) + [od] * (len(group) % 3)
    load.sum_od_mm = round(sum(widths), 1)
    load.kg_per_m = round(load.kg_per_m, 2)
    laid = sum(w * (1 + service.spacing_factor) for w in widths) / max(service.max_layers, 1)
    load.required_mm = round(laid * (1 + service.spare_pct / 100), 1)
    standard = sorted(service.widths_mm)
    if override and override.width_mm:
        load.width_mm = override.width_mm
    elif not widths:
        pass  # no cable here has a diameter: the width is not known
    elif standard:
        fits = next((w for w in standard if w >= load.required_mm), None)
        load.width_mm = fits or standard[-1]
        if fits is None:
            load.ladders = math.ceil(load.required_mm / standard[-1])
            load.flags.append(f"{load.ladders} ladders of {standard[-1]} mm")
    if load.width_mm:
        total = load.width_mm * load.ladders
        load.fill_pct = round(100 * laid / total, 1)
        if laid > total:
            load.flags.append("ladder too narrow")
        elif load.required_mm > total:
            load.flags.append("less than the spare left")
    limit = (override.max_kg_per_m if override and override.max_kg_per_m else service.max_kg_per_m)
    if limit is not None:
        load.max_kg_per_m = round(limit * load.ladders, 2)
        if load.kg_per_m > load.max_kg_per_m:
            load.flags.append("overloaded")
    if load.missing_od:
        load.flags.append(f"{len(load.missing_od)} cable(s) with no diameter")
    if load.missing_mass:
        load.flags.append(f"{len(load.missing_mass)} cable(s) with no mass")
    return load


def segment_loads(doc: CableRouting, cables: list[CableIn], routes: list[CableRoute]) -> list[SegmentLoad]:
    """Every segment's cables, and for each service on it the ladder width and the mass per metre."""
    by_row = {c.row: c for c in cables}
    on: dict[str, list[CableIn]] = {}
    for r in routes:
        if r.status in ("ok", "missing lengths"):
            for seg_id in dict.fromkeys(r.segments):
                on.setdefault(seg_id, []).append(by_row[r.row])
    out: list[SegmentLoad] = []
    for s in doc.segments:
        here = on.get(s.id, [])
        seg = SegmentLoad(id=s.id, tag=s.tag, length_m=s.length_m, cables=[c.row for c in here])
        for service in doc.services:
            mine = [c for c in here if c.service_id == service.id]
            if mine:
                seg.services.append(_ladder(service, s.ladders.get(service.id), mine))
        seg.width_mm = sum((x.width_mm or 0) * x.ladders for x in seg.services)
        seg.kg_per_m = round(sum(x.kg_per_m for x in seg.services), 2)
        flags = {f for x in seg.services for f in x.flags}
        seg.worst = ("" if not here else "over" if flags & {"overloaded", "ladder too narrow"}
                     else "full" if "less than the spare left" in flags else "ok")
        out.append(seg)
    return out


class Computed(BaseModel):
    cables: list[CableRoute] = Field(default_factory=list)
    segments: list[SegmentLoad] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def compute(doc: CableRouting, schedule: BuildResult, cable_types: list[CableType]) -> Computed:
    """The routes of a cable schedule's cables over the map, and the segments' ladders."""
    cables, warnings = cables_of(schedule, cable_types, doc)
    routes = route_cables(doc, cables)
    seen: dict[str, int] = {}
    for c in cables:
        if c.key:
            seen[c.key] = seen.get(c.key, 0) + 1
    shared = sorted(k.upper() for k, n in seen.items() if n > 1 and k in doc.overrides)
    if shared:
        warnings.append(f"A route is given for a cable number that several cables have: {', '.join(shared[:10])}.")
    return Computed(cables=routes, segments=segment_loads(doc, cables, routes), warnings=warnings)


def apply_routes(schedule: BuildResult, routes: list[CableRoute], allowance: Allowance) -> tuple[BuildResult, list[str]]:
    """The cable schedule with the routed cables' Length (m) (and Route, as the allowance says)
    from the map; the other cables keep what they have. Returns (the schedule, warnings)."""
    if LENGTH not in schedule.header:
        return schedule, [f"The Project Master Cable Schedule has no {LENGTH} column, so the routed lengths are not shown in it."]
    li = schedule.header.index(LENGTH)
    ri = schedule.header.index(ROUTE) if ROUTE in schedule.header and allowance.route_column != "never" else None
    rows = list(schedule.rows)
    for r in routes:
        if r.status != "ok" or r.length_m is None:
            continue
        cells = list(rows[r.row].cells)
        cells[li] = int(r.length_m) if float(r.length_m).is_integer() else r.length_m
        if ri is not None and (allowance.route_column == "always" or _text(cells[ri]) == ""):
            cells[ri] = r.route
        rows[r.row] = rows[r.row].model_copy(update={"cells": cells})
    return schedule.model_copy(update={"rows": rows}), []
