# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""The PLC List: PLC systems -> racks -> cards (by slot) -> IO points (one per channel).

It replaces the PLC hardware register each generator used to have (panel -> rack -> card);
the catalogue of card and rack types is the same shared one (generators.hardware). A card
has exactly as many IO points as its type has channels, numbered from 0 or from 1 as the
card type says (`first_channel`). Points belong to a card by position, so renumbering a type
keeps each point's tag and description.
"""

from __future__ import annotations

import io
import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from ..generators.hardware import Card, Catalogue, Hardware, Panel, Rack
from ..generators.models import Finding
from ..refdata.validate import name_key


def _id() -> str:
    return uuid.uuid4().hex[:12]


class IoPoint(BaseModel):
    channel: int
    tag: str = ""
    description: str = ""
    spare: bool = False


class PlcCard(BaseModel):
    id: str = Field(default_factory=_id)
    card_type_id: str
    tag: str = ""  # blank: named {RACK}-S{slot}
    spare: bool = False
    notes: str = ""
    points: list[IoPoint] = Field(default_factory=list)


class PlcRack(BaseModel):
    id: str = Field(default_factory=_id)
    tag: str
    plant_area_id: str | None = None
    rack_type_id: str
    description: str = ""
    first_slot: int = 1  # number of the first slot (cards fill slots in order)
    cards: list[PlcCard | None] = Field(default_factory=list)  # by slot; None = empty slot


class PlcSystem(BaseModel):
    id: str = Field(default_factory=_id)
    tag: str
    description: str = ""
    manufacturer: str = ""
    model: str = ""
    racks: list[PlcRack] = Field(default_factory=list)


class PlcList(BaseModel):
    systems: list[PlcSystem] = Field(default_factory=list)
    updated_at: datetime | None = None


def card_name(rack: PlcRack, slot: int, card: PlcCard) -> str:
    return card.tag.strip() or f"{rack.tag.strip()}-S{slot}"


def cards(plc: PlcList):
    """(system, rack, slot, card) for every card."""
    for s in plc.systems:
        for r in s.racks:
            for i, c in enumerate(r.cards):
                if c is not None:
                    yield s, r, r.first_slot + i, c


# -- IO points follow the card type --------------------------------------------------------------

def normalise_points(plc: PlcList, catalogue: Catalogue) -> tuple[PlcList, dict[str, str]]:
    """Give every card one IO point per channel of its type, numbered from the type's first
    channel (0 or 1), keeping the existing points in order. A point that would go but has a
    tag or description is an error (field `<card id>.card_type_id`) and is kept."""
    types = {t.id: t for t in catalogue.card_types}
    errors: dict[str, str] = {}
    plc = plc.model_copy(deep=True)
    for _s, rack, slot, card in cards(plc):
        t = types.get(card.card_type_id)
        n = len(card.points) if t is None else 0 if t.kind == "Network" else t.channels
        first = t.first_channel if t is not None else (card.points[0].channel if card.points else 0)
        old = sorted(card.points, key=lambda p: p.channel)
        lost = [p for p in old[n:] if p.tag.strip() or p.description.strip()]
        if lost:
            errors[f"{card.id}.card_type_id"] = (
                f"{card_name(rack, slot, card)}: channel(s) {', '.join(str(p.channel) for p in lost)} have a tag or "
                f"description, and the card type has {n} channel(s). Clear them first.")
        points = [(old[i] if i < len(old) else IoPoint(channel=0)).model_copy(update={"channel": first + i}) for i in range(n)]
        card.points = points + lost
    return plc, errors


# -- checks -----------------------------------------------------------------------------------

def check_plc(plc: PlcList, catalogue: Catalogue, plant_areas: set[str]) -> tuple[dict[str, str], list[Finding]]:
    """Errors (field -> message; they block a save) and findings (warnings shown with the list)."""
    errors: dict[str, str] = {}
    findings: list[Finding] = []
    rack_types = {t.id: t for t in catalogue.rack_types}
    card_types = {t.id: t for t in catalogue.card_types}

    def unique(items, key: str, label: str, field: str) -> None:
        seen: set[str] = set()
        for item_id, text in items:
            k = name_key(text)
            if not k:
                errors[f"{item_id}.{field}"] = f"{label} is required"
            elif k in seen:
                errors[f"{item_id}.{field}"] = f"{label} '{text.strip()}' is used twice"
            seen.add(k)

    unique([(s.id, s.tag) for s in plc.systems], "tag", "System tag", "tag")
    unique([(r.id, r.tag) for s in plc.systems for r in s.racks], "tag", "Rack tag", "tag")
    for s in plc.systems:
        for r in s.racks:
            where = f"{s.tag} / {r.tag}"
            rt = rack_types.get(r.rack_type_id)
            if rt is None:
                errors[f"{r.id}.rack_type_id"] = "The rack type is not in the catalogue"
            if r.plant_area_id is not None and r.plant_area_id not in plant_areas:
                errors[f"{r.id}.plant_area_id"] = "That plant area no longer exists"
            if r.plant_area_id is None:
                findings.append(Finding(severity="WARN", code="P1", item=r.tag or "(no tag)", detail="rack has no plant area",
                                        where=where))
            used = len(r.cards)
            while used and r.cards[used - 1] is None:
                used -= 1
            if rt is not None and rt.max_slots is not None and used > rt.max_slots:
                errors[f"{r.id}.cards"] = f"{used} slots used, the rack type has {rt.max_slots}"
            kinds = [card_types[c.card_type_id].kind for c in r.cards if c is not None and c.card_type_id in card_types]
            if any(k != "Network" for k in kinds) and "Network" not in kinds:
                findings.append(Finding(severity="WARN", code="P2", item=r.tag or "(no tag)",
                                        detail="rack has IO cards but no network adapter", where=where))
    names: dict[str, str] = {}
    points: dict[str, str] = {}
    for _s, rack, slot, card in cards(plc):
        if card.card_type_id not in card_types:
            errors[f"{card.id}.card_type_id"] = "The card type is not in the catalogue"
        name = card_name(rack, slot, card)
        if name_key(name) in names:
            errors[f"{card.id}.tag"] = f"Card name '{name}' is used twice"
        names[name_key(name)] = card.id
        for p in card.points:
            k = name_key(p.tag)
            if not k:
                continue
            if k in points:
                errors[f"{card.id}.points.{p.channel}"] = f"IO point tag '{p.tag.strip()}' is used twice"
            points[k] = card.id
    return errors, findings


# -- the old register's shape (schedules, the generators' IO demand check) -------------------------

def as_hardware(plc: PlcList) -> Hardware:
    """The PLC List as a generators.hardware register (system -> panel), for schedule() and
    summarise(). Cards carry their names, so schedules show the PLC List's names."""
    return Hardware(panels=[
        Panel(id=s.id, tag=s.tag, description=s.description, racks=[
            Rack(id=r.id, number=i + 1, rack_type_id=r.rack_type_id, description=r.tag, first_slot=r.first_slot,
                 cards=[None if c is None else Card(id=c.id, card_type_id=c.card_type_id,
                                                    tag=card_name(r, r.first_slot + j, c), spare=c.spare, notes=c.notes)
                        for j, c in enumerate(r.cards)])
            for i, r in enumerate(s.racks)])
        for s in plc.systems])


def from_registers(registers: list[Hardware], plant_areas: dict[str, str], catalogue: Catalogue) -> PlcList:
    """The generators' registers moved into one PLC List: a panel becomes a system (panels
    with the same tag are merged), its racks are tagged {PANEL}-R{n} (a rack already there
    is kept), and a rack's plant area is the one whose tag equals the panel's location.
    `plant_areas`: name_key(tag) -> id."""
    systems: dict[str, PlcSystem] = {}
    for hw in registers:
        for p in hw.panels:
            s = systems.get(name_key(p.tag))
            if s is None:
                s = systems[name_key(p.tag)] = PlcSystem(tag=p.tag.strip(), description=p.description)
            have = {name_key(r.tag) for r in s.racks}
            for r in p.racks:
                tag = f"{s.tag}-R{r.number}"
                if name_key(tag) in have:
                    continue
                have.add(name_key(tag))
                s.racks.append(PlcRack(
                    tag=tag, plant_area_id=plant_areas.get(name_key(p.location)), rack_type_id=r.rack_type_id,
                    description=r.description, first_slot=r.first_slot,
                    cards=[None if c is None else PlcCard(card_type_id=c.card_type_id, tag=c.tag, spare=c.spare, notes=c.notes)
                           for c in r.cards]))
    plc, _ = normalise_points(PlcList(systems=list(systems.values())), catalogue)
    return plc


# -- the workbook (export and import) ------------------------------------------------------------

PLC_HEAD = ["System", "System description", "Location", "Rack", "Rack type", "Rack description", "First slot",
            "Slot", "Card type", "Kind", "Channels", "Part number", "Name", "Spare", "Notes",
            "Rack tag", "Plant area", "Manufacturer", "Model"]
IO_HEAD = ["Rack tag", "Slot", "Card", "Channel", "Signal", "Tag", "Description", "Spare"]


def write_workbook(plc: PlcList, catalogue: Catalogue, area_tags: dict[str, str]) -> bytes:
    """Sheets "PLC cards" (one row per card, or per empty rack / system), "IO points" (one row
    per channel), "Card types" and "Rack types". `area_tags`: plant area id -> tag."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    from ..generators.bulk import Inputs, _w_card_types, _w_rack_types

    types = {t.id: t for t in catalogue.card_types}
    grid = [list(PLC_HEAD)]
    for s in plc.systems:
        tail = [s.manufacturer or None, s.model or None]
        if not s.racks:
            grid.append([s.tag, s.description, None] + [None] * 12 + [None, None] + tail)
        for i, r in enumerate(s.racks):
            base = [s.tag, s.description, None, i + 1, r.rack_type_id, r.description, r.first_slot]
            rtail = [r.tag, area_tags.get(r.plant_area_id or ""), *tail]
            filled = [(j, c) for j, c in enumerate(r.cards) if c is not None]
            if not filled:
                grid.append(base + [None] * 8 + rtail)
            for j, c in filled:
                t = types.get(c.card_type_id)
                grid.append(base + [r.first_slot + j, c.card_type_id, t.kind if t else None, t.channels if t else None,
                                    t.part_number if t else None, c.tag or None, "Yes" if c.spare else None,
                                    c.notes or None] + rtail)
    points = [list(IO_HEAD)]
    for _s, r, slot, c in cards(plc):
        kind = types[c.card_type_id].kind if c.card_type_id in types else None
        for p in c.points:
            points.append([r.tag, slot, card_name(r, slot, c), p.channel, kind, p.tag or None, p.description or None,
                           "Yes" if p.spare else None])
    inp = Inputs.model_construct(catalogue=catalogue)
    sheets = [("PLC cards", grid), ("IO points", points), ("Card types", _w_card_types(inp)[0]),
              ("Rack types", _w_rack_types(inp)[0])]
    wb = Workbook()
    wb.remove(wb.active)
    fill = PatternFill("solid", fgColor="E8EAED")
    for title, rows in sheets:
        ws = wb.create_sheet(title)
        for row in rows:
            ws.append(row)
        for c in ws[1]:
            c.font = Font(bold=True)
            c.fill = fill
        ws.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class ImportResult(BaseModel):
    plc: PlcList
    catalogue: Catalogue
    notes: list[str] = Field(default_factory=list)


def read_workbook(data: bytes, catalogue: Catalogue, plant_areas: dict[str, str]) -> ImportResult:
    """Read a workbook written by write_workbook, or a generator inputs workbook of before
    (its "PLC cards" sheet has Panel columns and no rack tags). Raises ValueError with the
    problem. `plant_areas`: name_key(tag) -> id."""
    from openpyxl import load_workbook

    from ..generators.bulk import Inputs, _r_card_types, _r_hardware, _r_rack_types, _sheet_grid, _t

    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 - any unreadable file
        raise ValueError("this is not an Excel workbook (.xlsx)") from exc
    sheets = {ws.title.strip().lower(): ws for ws in wb.worksheets}
    notes: list[str] = []
    cat = catalogue.model_copy(deep=True)
    inp = Inputs.model_construct(catalogue=cat)
    for title, reader, field in (("card types", _r_card_types, "card_types"), ("rack types", _r_rack_types, "rack_types")):
        if title in sheets:
            try:
                value, _ = reader(_sheet_grid(sheets[title]), inp)
            except ValueError as exc:
                raise ValueError(f"{title.capitalize()}: {exc}") from exc
            cat = cat.model_copy(update={field: value})
    if "plc cards" not in sheets:
        raise ValueError('the workbook has no "PLC cards" sheet')
    grid = _sheet_grid(sheets["plc cards"])
    if grid:  # accept the generator workbook's "Panel" headings too
        grid[0] = ["Panel" if i == 0 else "Panel description" if i == 1 else h for i, h in enumerate(grid[0])]
    try:
        hw, _ = _r_hardware(grid, inp, cat)
    except ValueError as exc:
        raise ValueError(f"PLC cards: {exc}") from exc
    # The extra columns: rack tag, plant area, manufacturer, model.
    extra: dict[tuple[str, int], tuple[str, str]] = {}
    makers: dict[str, tuple[str, str]] = {}
    for r in grid[1:]:
        r = list(r) + [None] * (len(PLC_HEAD) - len(r))
        tag = _t(r[0]).strip().lower()
        if not tag:
            continue
        if _t(r[17]).strip() or _t(r[18]).strip():
            makers[tag] = (_t(r[17]).strip(), _t(r[18]).strip())
        if _t(r[3]).strip():
            try:
                num = int(float(_t(r[3])))
            except ValueError:
                continue
            extra.setdefault((tag, num), (_t(r[15]).strip(), _t(r[16]).strip()))
    location = {name_key(p.tag): p.location for p in hw.panels}
    plc = from_registers([hw], plant_areas, cat)
    unknown: set[str] = set()
    for s in plc.systems:
        s.manufacturer, s.model = makers.get(s.tag.lower(), ("", ""))
        for r in s.racks:
            num = int(r.tag.rsplit("-R", 1)[1])
            tag, area = extra.get((s.tag.lower(), num), ("", ""))
            if tag:
                r.tag = tag
            area = area or location.get(name_key(s.tag), "")
            r.plant_area_id = plant_areas.get(name_key(area)) if area else None
            if area and r.plant_area_id is None:
                unknown.add(area)
    if unknown:
        notes.append(f"Plant area(s) not in Plant Areas, left blank: {', '.join(sorted(unknown))}")
    if "io points" in sheets:
        points: dict[tuple[str, int, int], tuple[str, str, bool]] = {}
        for r in _sheet_grid(sheets["io points"])[1:]:
            r = list(r) + [None] * (len(IO_HEAD) - len(r))
            try:
                key = (name_key(_t(r[0])), int(float(_t(r[1]))), int(float(_t(r[3]))))
            except ValueError:
                continue
            points[key] = (_t(r[5]).strip(), _t(r[6]).strip(), _t(r[7]).strip().lower() in ("yes", "y", "true", "1", "x"))
        for _s, rack, slot, card in cards(plc):
            for p in card.points:
                got = points.get((name_key(rack.tag), slot, p.channel))
                if got:
                    p.tag, p.description, p.spare = got
    else:
        notes.append('No "IO points" sheet: the IO points are created empty.')
    return ImportResult(plc=plc, catalogue=cat, notes=notes)
