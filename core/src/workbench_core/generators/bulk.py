# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Bulk editing in Excel (PRD 14.2): every input table of a generator in one workbook, one
sheet per table, and the import back with a per-sheet change preview.

Each table has a writer (model -> grid of cells) and a reader (grid -> model). The preview
compares the grid of the current model with the grid of the model read from the file, so it
shows exactly what applying would change. Sheets missing from the file are left alone."""

from __future__ import annotations

import io
import re
from collections import Counter
from dataclasses import dataclass
from typing import Callable

from pydantic import BaseModel, Field

from .hardware import Card, CardType, Catalogue, Hardware, Panel, Rack, RackType, default_catalogue
from .models import (CablePrefix, ColumnDef, DerivedTag, Generator, OutputColumn, RefTable, Route, RunRow, Runsheet,
                     Scalar, Template, TemplateCell, TemplateRow)
from .text import to_text

CALC = "ƒ"  # marks a calculated template cell ("ƒ concat"); calculations are defined per generator
SOURCE_ROW = "(source)"
ROW_ID = "Row ID"


class Inputs(BaseModel):
    generator: Generator  # with its lookup tables
    hardware: Hardware = Field(default_factory=Hardware)
    catalogue: Catalogue = Field(default_factory=default_catalogue)


class Change(BaseModel):
    key: str
    kind: str  # added | removed | changed
    cells: list[tuple[str, str, str]] = Field(default_factory=list)  # (column, old, new)


class SheetPreview(BaseModel):
    sheet: str
    table: str  # runsheet | templates | parents | derived | routes | prefixes | hardware | card_types | rack_types | table:<name>
    rows: int = 0
    added: int = 0
    removed: int = 0
    changed: int = 0
    changes: list[Change] = Field(default_factory=list)  # first 200
    errors: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @property
    def differs(self) -> bool:
        return bool(self.added or self.removed or self.changed)


class BulkPreview(BaseModel):
    sheets: list[SheetPreview] = Field(default_factory=list)
    ignored_sheets: list[str] = Field(default_factory=list)


Grid = list[list[Scalar]]


def _t(v: Scalar) -> str:
    return to_text(v)


def _blank(row: list[Scalar]) -> bool:
    return all(v is None or (isinstance(v, str) and v.strip() == "") for v in row)


def _trim(grid: Grid) -> Grid:
    rows = [list(r) for r in grid]
    while rows and _blank(rows[-1]):
        rows.pop()
    width = max((len(r) for r in rows), default=0)
    while width and all(len(r) < width or r[width - 1] is None or _t(r[width - 1]) == "" for r in rows):
        width -= 1
    return [r[:width] + [None] * (width - len(r)) for r in rows]


def _keys(raw: list[str]) -> list[str]:
    """Unique keys: duplicates get #2, #3 (as in the change report)."""
    seen: Counter = Counter()
    out = []
    for k in raw:
        seen[k] += 1
        out.append(k if seen[k] == 1 else f"{k}#{seen[k]}")
    return out


@dataclass
class TableDef:
    table: str
    sheet: str
    write: Callable[[Inputs], tuple[Grid, list[str], int]]  # (grid, keys of data rows, header rows)
    read: Callable[[Grid, Inputs], tuple[object, list[str]]]  # (value, notes); raises ValueError
    apply: Callable[[Inputs, object], None]


# -- runsheet ------------------------------------------------------------------------------

def _w_runsheet(inp: Inputs) -> tuple[Grid, list[str], int]:
    rs = inp.generator.runsheet
    grid: Grid = [[ROW_ID] + [c.name for c in rs.columns], [None] + [c.tag for c in rs.columns]]
    if any(c.source for c in rs.columns):
        grid.append([SOURCE_ROW] + [c.source for c in rs.columns])
    head = len(grid)
    n = len(rs.columns)
    for r in rs.rows:
        grid.append([r.id] + [r.values[i] if i < len(r.values) else None for i in range(n)])
    return grid, [r.id for r in rs.rows], head


def _r_runsheet(grid: Grid, inp: Inputs) -> tuple[Runsheet, list[str]]:
    if len(grid) < 2:
        raise ValueError("needs a labels row and a <<tags>> row")
    labels, tags = grid[0], grid[1]
    if _t(labels[0]).strip().lower() != ROW_ID.lower():
        raise ValueError(f"cell A1 must read '{ROW_ID}' (column A holds each run's id)")
    old = {(c.tag or "").strip().lower(): c for c in inp.generator.runsheet.columns if c.tag}
    cols = []
    start = 2
    sources = [None] * len(labels)
    if len(grid) > 2 and _t(grid[2][0]).strip().lower() == SOURCE_ROW:
        sources, start = grid[2], 3
    for i in range(1, len(labels)):
        tag = _t(tags[i]).strip() or None
        prev = old.get((tag or "").lower())
        cols.append(ColumnDef(name=_t(labels[i]) or (tag or f"Column {i}"), tag=tag,
                              source=_t(sources[i]) or None if i < len(sources) else None,
                              formula=prev.formula if prev else None))
    notes, rows, used = [], [], set()
    fresh = 0
    for r in grid[start:]:
        if _blank(r):
            continue
        rid = _t(r[0]).strip()
        if not rid or rid in used:
            fresh += 1
            rid = f"x{fresh}-{len(rows)}"
        used.add(rid)
        rows.append(RunRow(id=rid, values=[r[i] if i < len(r) else None for i in range(1, len(labels))]))
    if fresh:
        notes.append(f"{fresh} row(s) without a Row ID added as new runs")
    return Runsheet(columns=cols, rows=rows), notes


def _a_runsheet(inp: Inputs, v: Runsheet) -> None:
    inp.generator.runsheet = v


# -- templates -------------------------------------------------------------------------------

def _cell_out(c: TemplateCell | None, col: OutputColumn) -> Scalar:
    if c is None:
        return None
    if c.kind == "computed":
        comp = c.override or col.computed
        return f"{CALC} {comp.kind}" if comp else CALC
    return c.text if c.text is not None else c.value


def _w_templates(inp: Inputs) -> tuple[Grid, list[str], int]:
    g = inp.generator
    grid: Grid = [[g.id_column] + [c.name for c in g.output_columns]]
    keys = []
    block: Counter = Counter()
    prev = None
    for t in g.templates:
        if t.id != prev:
            block[t.id] += 1
        prev = t.id
        for seq, tr in enumerate(t.rows, start=1):
            grid.append([t.id_value] + [_cell_out(tr.cells[i] if i < len(tr.cells) else None, c)
                                        for i, c in enumerate(g.output_columns)])
            keys.append(f"{t.id} row {seq}" + (f" (block {block[t.id]})" if block[t.id] > 1 else ""))
    return grid, keys, 1


def _r_templates(grid: Grid, inp: Inputs) -> tuple[tuple[list[Template], list[OutputColumn]], list[str]]:
    if not grid:
        raise ValueError("no header row")
    g = inp.generator
    head = [_t(h).strip() for h in grid[0]]
    names = head[1:]
    if any(not n for n in names):
        raise ValueError("every column needs a header")
    dup = [n for n, k in Counter(x.lower() for x in names).items() if k > 1]
    if dup:
        raise ValueError(f"column header repeated: {', '.join(dup)}")
    old_cols = {c.name.lower(): c for c in g.output_columns}
    cols = [old_cols.get(n.lower(), OutputColumn(name=n)).model_copy(update={"name": n}) for n in names]
    notes = []
    added = [n for n in names if n.lower() not in old_cols]
    gone = [c.name for c in g.output_columns if c.name.lower() not in {n.lower() for n in names}]
    if added:
        notes.append(f"new output column(s): {', '.join(added)}")
    if gone:
        notes.append(f"output column(s) removed: {', '.join(gone)}")
    # current overrides, to keep per-row calculations when a row stays where it was
    old_over: dict[tuple[str, int, str], object] = {}
    old_src: dict[tuple[str, int], int | None] = {}
    for t in g.templates:
        for seq, tr in enumerate(t.rows, start=1):
            old_src.setdefault((t.id, seq), tr.source_row)
            for i, c in enumerate(tr.cells):
                if c.override is not None and i < len(g.output_columns):
                    old_over[(t.id, seq, g.output_columns[i].name.lower())] = c.override
    blocks: list[Template] = []
    for rnum, r in enumerate(grid[1:], start=2):
        if _blank(r):
            continue
        idv = r[0]
        tid = _t(idv).strip()
        if not tid:
            raise ValueError(f"row {rnum}: the {g.id_column} column is blank")
        if not blocks or blocks[-1].id != tid:
            blocks.append(Template(id=tid, id_value=idv, rows=[]))
        t = blocks[-1]
        seq = len(t.rows) + 1
        cells = []
        for i, col in enumerate(cols):
            v = r[i + 1] if i + 1 < len(r) else None
            if isinstance(v, str) and v.startswith(CALC):
                over = old_over.get((tid, seq, col.name.lower()))
                if col.computed is None and over is None:
                    raise ValueError(f"row {rnum}, column '{col.name}': marked calculated but the column has no calculation")
                cells.append(TemplateCell(kind="computed", override=over if col.computed is None or over else None))
            elif isinstance(v, str) and v.startswith("=") and len(v) > 1:
                cells.append(TemplateCell(kind="formula", text=v))
            elif isinstance(v, str) and "F=" in v:
                cells.append(TemplateCell(kind="late", text=v))
            elif isinstance(v, str) and "<<" in v:
                cells.append(TemplateCell(kind="text", text=v))
            else:
                cells.append(TemplateCell(kind="literal", value=v))
        t.rows.append(TemplateRow(cells=cells, source_row=old_src.get((tid, seq))))
    # mark IDs that appear in more than one block (the first block is used, as on import)
    counts = Counter(t.id for t in blocks)
    first: set[str] = set()
    for t in blocks:
        if t.id not in first:
            t.duplicate_blocks = counts[t.id] - 1
            first.add(t.id)
    return (blocks, cols), notes


def _a_templates(inp: Inputs, v: tuple[list[Template], list[OutputColumn]]) -> None:
    inp.generator.templates, inp.generator.output_columns = v


# -- small tables ----------------------------------------------------------------------------

def _simple(header: list[str], rows: Callable[[Inputs], list[list[Scalar]]], key: Callable[[list[Scalar]], str]):
    def w(inp: Inputs):
        data = rows(inp)
        return [list(header)] + data, _keys([key(r) for r in data]), 1

    def check_header(grid: Grid):
        if not grid or [_t(h).strip().lower() for h in grid[0][:len(header)]] != [h.lower() for h in header]:
            raise ValueError(f"the header row must be: {', '.join(header)}")
        return [r[:len(header)] + [None] * (len(header) - len(r)) for r in grid[1:] if not _blank(r)]
    return w, check_header


_w_parents, _h_parents = _simple(["Tag", "Description"],
                                 lambda i: [[t, d] for t, d in (i.generator.parents or [])], lambda r: _t(r[0]))


def _r_parents(grid: Grid, inp: Inputs):
    rows = _h_parents(grid)
    return [(_t(r[0]), _t(r[1])) for r in rows if _t(r[0]).strip()], []


def _a_parents(inp: Inputs, v) -> None:
    inp.generator.parents = v


_w_derived, _h_derived = _simple(["Name", "Source", "Transform", "Default"],
                                 lambda i: [[d.name, d.source, d.transform, d.default] for d in i.generator.derived_tags],
                                 lambda r: _t(r[0]))


def _r_derived(grid: Grid, inp: Inputs):
    return [DerivedTag(name=_t(r[0]), source=_t(r[1]), transform=_t(r[2]), default=_t(r[3]))
            for r in _h_derived(grid) if _t(r[0]).strip()], []


def _a_derived(inp: Inputs, v) -> None:
    inp.generator.derived_tags = v


_w_routes, _h_routes = _simple(["From", "To", "Length"],
                               lambda i: [[r.a, r.b, r.length] for r in i.generator.routes], lambda r: f"{_t(r[0])} | {_t(r[1])}")


def _r_routes(grid: Grid, inp: Inputs):
    out = []
    for n, r in enumerate(_h_routes(grid), start=2):
        if not _t(r[0]).strip():
            continue
        try:
            length = float(r[2])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"row {n}: Length must be a number") from exc
        out.append(Route(a=_t(r[0]), b=_t(r[1]), length=length))
    return out, []


def _a_routes(inp: Inputs, v) -> None:
    inp.generator.routes = v


_w_prefixes, _h_prefixes = _simple(["Cable type", "Prefix"],
                                   lambda i: [[p.cable_type, p.prefix] for p in i.generator.cable_prefixes], lambda r: _t(r[0]))


def _r_prefixes(grid: Grid, inp: Inputs):
    return [CablePrefix(cable_type=_t(r[0]), prefix=_t(r[1])) for r in _h_prefixes(grid) if _t(r[0]).strip()], []


def _a_prefixes(inp: Inputs, v) -> None:
    inp.generator.cable_prefixes = v


# -- PLC hardware and catalogue ------------------------------------------------------------------

HW_HEAD = ["Panel", "Panel description", "Location", "Rack", "Rack type", "Rack description", "First slot",
           "Slot", "Card type", "Kind", "Channels", "Part number", "Name", "Spare", "Notes"]


def _w_hardware(inp: Inputs):
    cards = {t.id: t for t in inp.catalogue.card_types}
    grid: Grid = [list(HW_HEAD)]
    keys = []
    for p in inp.hardware.panels:
        if not p.racks:
            grid.append([p.tag, p.description, p.location] + [None] * 12)
            keys.append(p.tag)
        for r in p.racks:
            filled = [(i, c) for i, c in enumerate(r.cards) if c is not None]
            base = [p.tag, p.description, p.location, r.number, r.rack_type_id, r.description, r.first_slot]
            if not filled:
                grid.append(base + [None] * 8)
                keys.append(f"{p.tag} R{r.number}")
            for i, c in filled:
                t = cards.get(c.card_type_id)
                grid.append(base + [r.first_slot + i, c.card_type_id, t.kind if t else None, t.channels if t else None,
                                    t.part_number if t else None, c.tag or None, "Yes" if c.spare else None, c.notes or None])
                keys.append(f"{p.tag} R{r.number} S{r.first_slot + i}")
    return grid, keys, 1


def resolve_card_type(value: str, cat: Catalogue) -> str | None:
    v = value.strip()
    if not v:
        return None
    lv = v.lower()
    for t in cat.card_types:
        if t.id.lower() == lv:
            return t.id
    for t in cat.card_types:
        if t.part_number.strip() and t.part_number.strip().lower() == lv:
            return t.id
    m = re.fullmatch(r"(network|di|do|ai|ao|rtd)\s*-?\s*(\d*)", lv)
    if m:
        kind, n = m.group(1), int(m.group(2) or 0)
        for t in cat.card_types:
            if t.kind.lower() == kind and (t.channels == n or (kind == "network" and not m.group(2))):
                return t.id
    return None


def resolve_rack_type(value: str, cat: Catalogue) -> str | None:
    lv = value.strip().lower()
    if not lv:
        return cat.rack_types[0].id if cat.rack_types else None
    for t in cat.rack_types:
        if lv in (t.id.lower(), t.part_number.strip().lower(), t.description.strip().lower()):
            return t.id
    return None


def _int(v: Scalar, what: str, row: int) -> int:
    try:
        f = float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"row {row}: {what} must be a whole number") from exc
    if f != int(f):
        raise ValueError(f"row {row}: {what} must be a whole number")
    return int(f)


def _r_hardware(grid: Grid, inp: Inputs, cat: Catalogue | None = None):
    cat = cat or inp.catalogue
    if not grid or [_t(h).strip().lower() for h in grid[0][:9]] != [h.lower() for h in HW_HEAD[:9]]:
        raise ValueError(f"the header row must start: {', '.join(HW_HEAD[:9])}")
    panels: dict[str, Panel] = {}
    racks: dict[tuple[str, int], Rack] = {}
    slots: set[tuple[str, int, int]] = set()
    for n, r in enumerate(grid[1:], start=2):
        if _blank(r):
            continue
        r = r + [None] * (len(HW_HEAD) - len(r))
        tag = _t(r[0]).strip()
        if not tag:
            raise ValueError(f"row {n}: Panel is blank")
        p = panels.get(tag.lower())
        if p is None:
            p = panels[tag.lower()] = Panel(tag=tag, description=_t(r[1]), location=_t(r[2]))
        if r[3] is None or _t(r[3]).strip() == "":
            continue
        num = _int(r[3], "Rack", n)
        rack = racks.get((tag.lower(), num))
        if rack is None:
            rt = resolve_rack_type(_t(r[4]), cat)
            if rt is None:
                raise ValueError(f"row {n}: rack type '{_t(r[4])}' is not in the catalogue")
            first = _int(r[6], "First slot", n) if _t(r[6]).strip() else 1
            rack = racks[(tag.lower(), num)] = Rack(number=num, rack_type_id=rt, description=_t(r[5]), first_slot=first)
            p.racks.append(rack)
        if r[7] is None or _t(r[7]).strip() == "":
            continue
        slot = _int(r[7], "Slot", n)
        if slot < rack.first_slot:
            raise ValueError(f"row {n}: slot {slot} is below the rack's first slot {rack.first_slot}")
        if (tag.lower(), num, slot) in slots:
            raise ValueError(f"row {n}: {tag} rack {num} slot {slot} is used twice")
        slots.add((tag.lower(), num, slot))
        ct = resolve_card_type(_t(r[8]), cat)
        if ct is None:
            raise ValueError(f"row {n}: card type '{_t(r[8])}' is not in the catalogue (use its ID, part number or e.g. DI16)")
        idx = slot - rack.first_slot
        while len(rack.cards) <= idx:
            rack.cards.append(None)
        spare = _t(r[13]).strip().lower() in ("yes", "y", "true", "1", "x", "spare")
        rack.cards[idx] = Card(card_type_id=ct, tag=_t(r[12]).strip(), spare=spare, notes=_t(r[14]))
    return Hardware(panels=list(panels.values())), []


def _a_hardware(inp: Inputs, v) -> None:
    inp.hardware = v


CT_HEAD = ["ID", "Kind", "Channels", "Part number", "Description", "Wiring"]
CT_FIRST = "First channel"  # an extra column (sheets without it are read as 0)
RT_HEAD = ["ID", "Part number", "Description", "Max slots"]


def _w_card_types(inp: Inputs):
    rows = [[t.id, t.kind, t.channels, t.part_number, t.description, t.wiring, t.first_channel]
            for t in inp.catalogue.card_types]
    return [list(CT_HEAD) + [CT_FIRST]] + rows, [r[0] for r in rows], 1


def _r_card_types(grid: Grid, inp: Inputs):
    if not grid or [_t(h).strip().lower() for h in grid[0][:6]] != [h.lower() for h in CT_HEAD]:
        raise ValueError(f"the header row must be: {', '.join(CT_HEAD)}")
    out, ids = [], set()
    kinds = {k.lower(): k for k in ["Network", "DI", "DO", "AI", "AO", "RTD"]}
    for n, r in enumerate(grid[1:], start=2):
        if _blank(r):
            continue
        r = r + [None] * (7 - len(r))
        kind = kinds.get(_t(r[1]).strip().lower())
        if kind is None:
            raise ValueError(f"row {n}: Kind must be one of Network, DI, DO, AI, AO, RTD")
        ch = _int(r[2], "Channels", n) if _t(r[2]).strip() else 0
        if ch < 0:
            raise ValueError(f"row {n}: Channels can't be negative")
        first = _int(r[6], CT_FIRST, n) if _t(r[6]).strip() else 0
        if first not in (0, 1):
            raise ValueError(f"row {n}: {CT_FIRST} must be 0 or 1")
        kw = dict(kind=kind, channels=ch, part_number=_t(r[3]), description=_t(r[4]), wiring=_t(r[5]), first_channel=first)
        tid = _t(r[0]).strip()
        t = CardType(id=tid, **kw) if tid else CardType(**kw)
        if t.id in ids:
            raise ValueError(f"row {n}: ID {t.id} is used twice")
        ids.add(t.id)
        out.append(t)
    return out, []


def _a_card_types(inp: Inputs, v) -> None:
    inp.catalogue = inp.catalogue.model_copy(update={"card_types": v})


def _w_rack_types(inp: Inputs):
    rows = [[t.id, t.part_number, t.description, t.max_slots] for t in inp.catalogue.rack_types]
    return [list(RT_HEAD)] + rows, [r[0] for r in rows], 1


def _r_rack_types(grid: Grid, inp: Inputs):
    if not grid or [_t(h).strip().lower() for h in grid[0][:4]] != [h.lower() for h in RT_HEAD]:
        raise ValueError(f"the header row must be: {', '.join(RT_HEAD)}")
    out, ids = [], set()
    for n, r in enumerate(grid[1:], start=2):
        if _blank(r):
            continue
        r = r + [None] * (4 - len(r))
        mx = _int(r[3], "Max slots", n) if _t(r[3]).strip() else None
        if mx is not None and mx < 1:
            raise ValueError(f"row {n}: Max slots must be at least 1 (or blank)")
        tid = _t(r[0]).strip()
        kw = dict(part_number=_t(r[1]), description=_t(r[2]), max_slots=mx)
        t = RackType(id=tid, **kw) if tid else RackType(**kw)
        if t.id in ids:
            raise ValueError(f"row {n}: ID {t.id} is used twice")
        ids.add(t.id)
        out.append(t)
    return out, []


def _a_rack_types(inp: Inputs, v) -> None:
    inp.catalogue = inp.catalogue.model_copy(update={"rack_types": v})


# -- lookup tables ------------------------------------------------------------------------------

def table_sheet(name: str) -> str:
    return ("T " + re.sub(r"[\[\]:*?/\\]", "_", name))[:31]


def _lookup_def(name: str) -> TableDef:
    def w(inp: Inputs):
        t = inp.generator.tables.get(name)
        rows = [list(r) for r in (t.rows if t else [])]
        return rows, [f"row {i + 1}" for i in range(len(rows))], 0

    def r(grid: Grid, inp: Inputs):
        old = inp.generator.tables.get(name)
        width = max((len(x) for x in grid), default=0)
        from openpyxl.utils import get_column_letter
        cols = [get_column_letter(i + 1) for i in range(max(width, len(old.columns) if old else 0))]
        return RefTable(name=name, columns=cols, rows=[list(x) for x in grid], first_column=1), []

    def a(inp: Inputs, v) -> None:
        inp.generator.tables[name] = v
    return TableDef(f"table:{name}", table_sheet(name), w, r, a)


def table_defs(inp: Inputs) -> list[TableDef]:
    defs = [
        TableDef("runsheet", "RunSheet", _w_runsheet, _r_runsheet, _a_runsheet),
        TableDef("templates", "Templates", _w_templates, _r_templates, _a_templates),
        TableDef("parents", "Parents", _w_parents, _r_parents, _a_parents),
        TableDef("derived", "Derived tags", _w_derived, _r_derived, _a_derived),
        TableDef("routes", "Routes", _w_routes, _r_routes, _a_routes),
        TableDef("prefixes", "Cable prefixes", _w_prefixes, _r_prefixes, _a_prefixes),
    ]
    defs += [_lookup_def(n) for n in sorted(inp.generator.tables)]
    return defs


# -- workbook ------------------------------------------------------------------------------------

ABOUT = [
    "Bulk editing workbook for the generator \"{name}\".",
    "",
    "Edit the sheets, save, and import the file back (Generators > Import inputs). Before anything is",
    "saved you see, for each sheet, the rows added, removed and changed, and choose which sheets to apply.",
    "A sheet you delete from the workbook is left unchanged in the app.",
    "",
    "RunSheet: row 1 labels, row 2 <<TAGS>> (a column with a <<TAG>> is a tag), then one row per run.",
    "  Column A (Row ID) identifies each run; leave it blank on new rows.",
    "Templates: one row per template row; rows with the same ID next to each other form a template.",
    "  Text with <<TAGS>> is expanded; F= starts a late formula; cells starting with " + CALC + " are calculated",
    "  by the generator (leave them as they are, or clear them).",
    "PLC cards and the card / rack types are not in this workbook: they are in the project's PLC List",
    "  (Project lists > PLC List, which has its own Excel export and import).",
    "T <name>: the generator's lookup tables, cell for cell (row 1 is the sheet's first row).",
]


def write_inputs(inp: Inputs, name: str = "") -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    about = wb.active
    about.title = "About"
    for line in ABOUT:
        about.append([line.format(name=name)])
    about["A1"].font = Font(bold=True)
    about.column_dimensions["A"].width = 110
    head_fill = PatternFill("solid", fgColor="E8EAED")
    for d in table_defs(inp):
        grid, _keys_, head = d.write(inp)
        ws = wb.create_sheet(d.sheet)
        for r in grid:
            ws.append(list(r))
        for row in ws.iter_rows():
            for c in row:
                if isinstance(c.value, str) and c.value.startswith("="):
                    c.data_type = "s"  # text, not a live formula
        for rr in range(1, head + 1):
            for c in ws[rr]:
                c.font = Font(bold=True)
                c.fill = head_fill
        if head:
            ws.freeze_panes = ws.cell(row=head + 1, column=2 if d.table == "runsheet" else 1)
        for i in range(1, ws.max_column + 1):
            w = max((len(_t(ws.cell(row=r, column=i).value)) for r in range(1, min(ws.max_row, 300) + 1)), default=8)
            ws.column_dimensions[get_column_letter(i)].width = min(45, max(8, w + 2))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _sheet_grid(ws) -> Grid:
    from .xlsx_import import _clean
    return _trim([[_clean(v) for v in r] for r in ws.iter_rows(values_only=True)])


def _grid_text(grid: Grid, keys: list[str], head: int) -> tuple[list[str], dict[str, list[str]]]:
    header = [_t(h) for h in grid[0]] if grid and head else []
    rows = {}
    for k, r in zip(keys, grid[head:]):
        rows[k] = [_t(v) for v in r]
    return header, rows


def _diff(sheet: str, table: str, old: tuple[Grid, list[str], int], new: tuple[Grid, list[str], int]) -> SheetPreview:
    oh, orows = _grid_text(*old)
    nh, nrows = _grid_text(*new)
    sp = SheetPreview(sheet=sheet, table=table, rows=len(nrows))
    width = max([len(oh), len(nh)] + [len(r) for r in orows.values()] + [len(r) for r in nrows.values()] + [0])
    names = [(nh[i] if i < len(nh) and nh[i] else oh[i] if i < len(oh) and oh[i] else f"column {i + 1}") for i in range(width)]
    if oh != nh and old[2]:
        sp.changes.append(Change(key="(header)", kind="changed",
                                 cells=[(f"column {i + 1}", oh[i] if i < len(oh) else "", nh[i] if i < len(nh) else "")
                                        for i in range(width) if (oh[i] if i < len(oh) else "") != (nh[i] if i < len(nh) else "")]))
        sp.changed += 1
    for k, r in nrows.items():
        if k not in orows:
            sp.added += 1
            sp.changes.append(Change(key=k, kind="added"))
            continue
        o = orows[k]
        cells = [(names[i], o[i] if i < len(o) else "", r[i] if i < len(r) else "") for i in range(width)
                 if (o[i] if i < len(o) else "") != (r[i] if i < len(r) else "")]
        if cells:
            sp.changed += 1
            sp.changes.append(Change(key=k, kind="changed", cells=cells))
    for k in orows:
        if k not in nrows:
            sp.removed += 1
            sp.changes.append(Change(key=k, kind="removed"))
    sp.changes = sp.changes[:200]
    return sp


def read_inputs(data: bytes, current: Inputs) -> tuple[BulkPreview, dict[str, object]]:
    """Preview of every recognised sheet, and the parsed values (by table id) of sheets without errors."""
    import warnings

    from openpyxl import load_workbook
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            wb = load_workbook(io.BytesIO(data), data_only=False)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Not an Excel workbook (.xlsx): {exc}") from exc
    defs = {d.sheet.lower(): d for d in table_defs(current)}
    preview = BulkPreview()
    parsed: dict[str, object] = {}
    # catalogue sheets first, so the PLC cards sheet can use new card types from the same file
    order = sorted(wb.sheetnames, key=lambda s: 0 if s.lower() in ("card types", "rack types") else 1)
    cat = current.catalogue.model_copy(deep=True)
    for name in order:
        d = defs.get(name.lower())
        if d is None:
            if name.lower() != "about":
                preview.ignored_sheets.append(name)
            continue
        grid = _sheet_grid(wb[name])
        try:
            if d.table == "hardware":
                value, notes = _r_hardware(grid, current, cat)
            else:
                value, notes = d.read(grid, current)
        except ValueError as exc:
            preview.sheets.append(SheetPreview(sheet=d.sheet, table=d.table, errors=[str(exc)]))
            continue
        after = current.model_copy(deep=True)
        after.catalogue = cat
        d.apply(after, value)
        if d.table in ("card_types", "rack_types"):
            cat = after.catalogue
        sp = _diff(d.sheet, d.table, d.write(current), d.write(after))
        sp.notes = notes
        preview.sheets.append(sp)
        parsed[d.table] = value
    rank = {d.table: i for i, d in enumerate(table_defs(current))}
    preview.sheets.sort(key=lambda s: rank.get(s.table, 99))
    return preview, parsed


def apply_inputs(current: Inputs, parsed: dict[str, object], tables: list[str]) -> Inputs:
    """A copy of `current` with the chosen parsed tables applied (catalogue before hardware)."""
    out = current.model_copy(deep=True)
    defs = {d.table: d for d in table_defs(current)}
    for t in sorted(tables, key=lambda x: 0 if x in ("card_types", "rack_types") else 1):
        if t in parsed and t in defs:
            defs[t].apply(out, parsed[t])
    return out
