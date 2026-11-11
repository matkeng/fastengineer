# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""PLC hardware register: a catalogue of rack and card types, and the panels, racks and
cards installed (panel -> rack -> slot -> card). The first step of IO card allocation
(PRD 6.7); points are not assigned to channels yet."""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from typing import Literal

from pydantic import BaseModel, Field

from .models import BuildResult, Finding
from .text import to_text

CardKind = Literal["Network", "DI", "DO", "AI", "AO", "RTD"]
CARD_KINDS: list[str] = ["Network", "DI", "DO", "AI", "AO", "RTD"]
IO_SIZES = [8, 12, 16, 32]
KIND_NAMES = {"Network": "Network adapter", "DI": "Digital input", "DO": "Digital output",
              "AI": "Analog input", "AO": "Analog output", "RTD": "RTD input"}


def _id() -> str:
    return uuid.uuid4().hex[:12]


class CardType(BaseModel):
    id: str = Field(default_factory=_id)
    kind: CardKind
    channels: int = 0  # IO channels (0 for a network adapter)
    part_number: str = ""
    description: str = ""
    wiring: str = ""  # analog wiring, e.g. "2-wire", "2/3/4-wire"
    first_channel: Literal[0, 1] = 0  # channels are numbered from 0 or from 1 (as the card's maker does)


class RackType(BaseModel):
    id: str = Field(default_factory=_id)
    part_number: str = ""
    description: str = ""
    max_slots: int | None = None  # None: as many cards as needed (modular racks)


class Catalogue(BaseModel):
    rack_types: list[RackType] = Field(default_factory=list)
    card_types: list[CardType] = Field(default_factory=list)


def default_catalogue() -> Catalogue:
    """Generic types to start from; part numbers are left for the project to fill in."""
    cards = [CardType(id="net", kind="Network", channels=0, description="Network adapter")]
    for kind in ["DI", "DO", "AI", "AO", "RTD"]:
        for n in IO_SIZES:
            cards.append(CardType(id=f"{kind.lower()}{n}", kind=kind, channels=n,
                                  description=f"{KIND_NAMES[kind]}, {n} channels",
                                  wiring="2/3/4-wire" if kind in ("AI", "AO", "RTD") else ""))
    return Catalogue(rack_types=[RackType(id="rack", description="Modular rack")], card_types=cards)


class Card(BaseModel):
    id: str = Field(default_factory=_id)
    card_type_id: str
    tag: str = ""  # blank: named {PANEL}-R{rack}-S{slot}
    spare: bool = False
    notes: str = ""


class Rack(BaseModel):
    id: str = Field(default_factory=_id)
    number: int = 1
    rack_type_id: str
    description: str = ""
    first_slot: int = 1  # number of the first slot (cards fill slots in order)
    cards: list[Card | None] = Field(default_factory=list)  # by slot; None = empty slot


class Panel(BaseModel):
    id: str = Field(default_factory=_id)
    tag: str
    description: str = ""
    location: str = ""
    racks: list[Rack] = Field(default_factory=list)


class Hardware(BaseModel):
    panels: list[Panel] = Field(default_factory=list)


# -- names, schedule, checks, summaries -------------------------------------------------

def card_name(panel: Panel, rack: Rack, slot: int, card: Card) -> str:
    return card.tag.strip() or f"{panel.tag}-R{rack.number}-S{slot}"


class ScheduleRow(BaseModel):
    panel: str
    rack: int
    slot: int
    card: str
    kind: str
    channels: int
    part_number: str
    description: str
    spare: bool
    notes: str


def schedule(hw: Hardware, cat: Catalogue) -> list[ScheduleRow]:
    types = {t.id: t for t in cat.card_types}
    out = []
    for p in hw.panels:
        for r in p.racks:
            for i, c in enumerate(r.cards):
                if c is None:
                    continue
                t = types.get(c.card_type_id)
                slot = r.first_slot + i
                out.append(ScheduleRow(panel=p.tag, rack=r.number, slot=slot, card=card_name(p, r, slot, c),
                                       kind=t.kind if t else "?", channels=t.channels if t else 0,
                                       part_number=t.part_number if t else "", description=t.description if t else "",
                                       spare=c.spare, notes=c.notes))
    return out


def check_hardware(hw: Hardware, cat: Catalogue) -> list[Finding]:
    f: list[Finding] = []
    racks = {t.id: t for t in cat.rack_types}
    cards = {t.id: t for t in cat.card_types}

    def add(sev, code, item, detail, where=""):
        f.append(Finding(severity=sev, code=code, item=item, detail=detail, where=where))

    for tag, n in Counter(p.tag.strip().lower() for p in hw.panels).items():
        if n > 1:
            add("ERROR", "H1", tag.upper(), f"panel tag used {n} times")
    for p in hw.panels:
        if not p.tag.strip():
            add("ERROR", "H1", "(blank)", "a panel has no tag")
        for num, n in Counter(r.number for r in p.racks).items():
            if n > 1:
                add("ERROR", "H2", f"{p.tag} rack {num}", f"rack number used {n} times", p.tag)
        for r in p.racks:
            rt = racks.get(r.rack_type_id)
            where = f"{p.tag} rack {r.number}"
            if rt is None:
                add("ERROR", "H3", where, "rack type is not in the catalogue", where)
            used = len(r.cards)
            while used and r.cards[used - 1] is None:
                used -= 1
            if rt is not None and rt.max_slots is not None and used > rt.max_slots:
                add("ERROR", "H4", where, f"{used} slots used, the rack type has {rt.max_slots}", where)
            for i, c in enumerate(r.cards):
                if c is not None and c.card_type_id not in cards:
                    add("ERROR", "H5", f"{where} slot {r.first_slot + i}", "card type is not in the catalogue", where)
            io = [c for c in r.cards if c is not None and cards.get(c.card_type_id) and cards[c.card_type_id].kind != "Network"]
            nets = [c for c in r.cards if c is not None and cards.get(c.card_type_id) and cards[c.card_type_id].kind == "Network"]
            if io and not nets:
                add("WARN", "H6", where, "rack has IO cards but no network adapter", where)
    names = Counter(row.card.lower() for row in schedule(hw, cat))
    for name, n in names.items():
        if n > 1:
            add("ERROR", "H7", name.upper(), f"card name used {n} times")
    for kind, n in Counter((t.kind, t.channels, t.part_number.strip().lower()) for t in cat.card_types if t.part_number.strip()).items():
        if n > 1:
            add("WARN", "H8", kind[2].upper(), "part number used by more than one card type")
    return f


class KindTotal(BaseModel):
    kind: str
    cards: int = 0
    channels: int = 0
    spare_cards: int = 0


class Demand(BaseModel):
    """IO points in the latest IO list build per CARD TYPE value, against installed channels."""
    card_type: str  # the value in the IO list (matched to catalogue part numbers)
    points: int
    kind: str | None = None  # catalogue kind when the value matches a part number
    channels: int = 0  # installed channels of matching card types
    free: int = 0


class HardwareSummary(BaseModel):
    panels: int = 0
    racks: int = 0
    cards: int = 0
    by_kind: list[KindTotal] = Field(default_factory=list)
    demand: list[Demand] = Field(default_factory=list)
    demand_column: str | None = None


def summarise(hw: Hardware, cat: Catalogue, build: BuildResult | None = None,
              card_column: str = "CARD TYPE") -> HardwareSummary:
    rows = schedule(hw, cat)
    s = HardwareSummary(panels=len(hw.panels), racks=sum(len(p.racks) for p in hw.panels), cards=len(rows))
    kinds: dict[str, KindTotal] = {k: KindTotal(kind=k) for k in CARD_KINDS}
    for r in rows:
        k = kinds.setdefault(r.kind, KindTotal(kind=r.kind))
        k.cards += 1
        k.channels += r.channels
        k.spare_cards += r.spare
    s.by_kind = [k for k in kinds.values() if k.cards]
    if build is not None:
        hl = [h.lower() for h in build.header]
        if card_column.lower() in hl:
            ci = hl.index(card_column.lower())
            s.demand_column = build.header[ci]
            pts = Counter(to_text(r.cells[ci]).strip() for r in build.rows
                          if r.run_row_id is not None and ci < len(r.cells) and to_text(r.cells[ci]).strip())
            by_part: dict[str, list[CardType]] = defaultdict(list)
            for t in cat.card_types:
                if t.part_number.strip():
                    by_part[t.part_number.strip().lower()].append(t)
            installed: Counter = Counter()
            for r in rows:
                if r.part_number.strip():
                    installed[r.part_number.strip().lower()] += r.channels
            for value, n in sorted(pts.items()):
                ts = by_part.get(value.lower(), [])
                ch = installed.get(value.lower(), 0)
                s.demand.append(Demand(card_type=value, points=n, kind=ts[0].kind if ts else None,
                                       channels=ch, free=ch - n))
    return s
