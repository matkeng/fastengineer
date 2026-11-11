# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""The project lists as Excel workbooks: export a list, edit it in Excel, import it back.

A workbook says things by name (a plant area by its tag number, a load type by its code, a
package by its number), never by the ids the lists use between themselves. On import each
row is matched to the item of the list with the same name, which keeps that item's id, so
whatever refers to it (the Load List, the Electrical Equipment List, a deliverable) still
does. An import replaces the list with what the file says: rows not in the file go, and the
result passes the same checks as a save in the app (the engine does that, see
keylist_workbooks_api).

Each `export_*` gives the sheets to write; each `import_*` reads them back into what the
list's save takes, and raises ValueError naming what is wrong with the file. (The PLC List
has its own workbook, in keylists.plc.)
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

from ..refdata.models import new_id
from ..refdata.validate import name_key
from .cable_types import CableType
from .distribution_panels import (KIND_LABELS, DistributionPanel, DistributionPanelList, PanelDivider, PanelEntry, PoleValues,
                                  circuit_name)
from .loadgen import LISTS, ROW_SETTINGS, TEMPLATE_LISTS, ordered
from .loadlist import CABLE_CONSTRUCTIONS, EEL_SOURCE, PRIMARY_SUPPLY, LoadListRow
from .models import (DISCIPLINES, EelList, EquipmentCode, EquipmentPackageList, InstrumentCode, LoadTypeList, PlantArea,
                     PlantAreaList)
from .panel_calc import POLES

Grid = list[list]
Sheets = list[tuple[str, Grid]]
Rows = list[dict[str, str]]
PRIMARY = "Primary Supply"
_YES = ("yes", "y", "true", "1", "x")


@dataclass
class Parsed:
    """What a file says: `payload` is what the list's save takes; `keys` the names of its main
    items (to say what is new and what goes); `notes` what the person should know."""
    payload: object
    keys: list[str]
    notes: list[str] = field(default_factory=list)
    labels: dict[str, str] = field(default_factory=dict)  # item id -> its name, for error messages


# -- reading and writing ---------------------------------------------------------------------------

def write_sheets(sheets: Sheets) -> bytes:
    """One sheet per (title, grid); the first row of a grid is its bold, frozen heading."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    wb.remove(wb.active)
    fill = PatternFill("solid", fgColor="E8EAED")
    for title, grid in sheets:
        ws = wb.create_sheet(title[:31])
        for row in grid:
            ws.append([("'" + v) if isinstance(v, str) and v.startswith("=") else v for v in row])
        for c in ws[1]:
            c.font = Font(bold=True)
            c.fill = fill
        ws.freeze_panes = "A2"
        for i in range(len(grid[0]) if grid else 0):
            width = max(len(str(r[i])) for r in grid[:300] if i < len(r) and r[i] is not None) if grid else 8
            ws.column_dimensions[get_column_letter(i + 1)].width = min(60, max(8, width + 2))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _text(v: object) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return str(v).strip()


def read_sheets(data: bytes) -> dict[str, Rows]:
    """Sheet title (lower case) -> its rows as {heading (lower case): text}. Blank rows are
    skipped. Raises ValueError if the file is not a workbook."""
    from openpyxl import load_workbook

    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 - any unreadable file
        raise ValueError("this is not an Excel workbook (.xlsx)") from exc
    out: dict[str, Rows] = {}
    for ws in wb.worksheets:
        rows = ws.iter_rows(values_only=True)
        head = [_text(h).casefold() for h in next(rows, ())]
        out[ws.title.strip().casefold()] = [
            {h: _text(v) for h, v in zip(head, r) if h} for r in rows if any(_text(v) for v in r)]
    return out


def _sheet(sheets: dict[str, Rows], title: str, need: tuple[str, ...]) -> Rows:
    rows = sheets.get(title.casefold())
    if rows is None:
        raise ValueError(f'the workbook has no "{title}" sheet')
    if rows:
        missing = [n for n in need if n.casefold() not in rows[0]]
        if missing:
            raise ValueError(f'the "{title}" sheet has no column called {", ".join(missing)}')
    return rows


def _get(row: dict[str, str], heading: str) -> str:
    return row.get(heading.casefold(), "")


def _yes(text: str) -> bool:
    return text.strip().casefold() in _YES


class _Names:
    """Names (a tag, a code...) -> ids, ignoring case and extra spaces; collects the unknown ones."""

    def __init__(self, what: str, pairs: list[tuple[str, str]]):
        self.what = what
        self.ids = {name_key(name): i for i, name in pairs if name_key(name)}
        self.unknown: set[str] = set()

    def get(self, name: str) -> str | None:
        if not name.strip():
            return None
        found = self.ids.get(name_key(name))
        if found is None:
            self.unknown.add(name.strip())
        return found

    def note(self, notes: list[str], then: str = "left blank") -> None:
        if self.unknown:
            notes.append(f"{self.what} not found, {then}: {', '.join(sorted(self.unknown)[:12])}"
                         + (f" and {len(self.unknown) - 12} more" if len(self.unknown) > 12 else ""))


def _keep(old: list[tuple[str, str]]):
    """A function giving the id of the existing item with a name, or a new id (once per name)."""
    ids = {name_key(name): i for i, name in old}
    used: set[str] = set()

    def get(name: str) -> str:
        found = ids.get(name_key(name))
        if found is None or found in used:
            return new_id()
        used.add(found)
        return found
    return get


# -- Plant Areas -----------------------------------------------------------------------------------

AREA_HEAD = ["Tag number", "Description", "Type", "WBS number", "Parent tag"]


def export_plant_areas(areas: PlantAreaList) -> Sheets:
    tags = {n.id: n.tag for n in areas.nodes}
    return [("Plant Areas", [AREA_HEAD] + [[n.tag, n.description, n.area_type, n.wbs or None, tags.get(n.parent_id or "")]
                                           for n in areas.nodes])]


def import_plant_areas(sheets: dict[str, Rows], old: PlantAreaList) -> Parsed:
    rows = _sheet(sheets, "Plant Areas", ("Tag number", "Description", "Type"))
    keep = _keep([(n.id, n.tag) for n in old.nodes])
    ids = {name_key(_get(r, "Tag number")): keep(_get(r, "Tag number")) for r in rows}
    children: dict[str | None, list[dict]] = {}
    for r in rows:
        parent = _get(r, "Parent tag")
        if parent and name_key(parent) not in ids:
            raise ValueError(f"Plant Areas: {_get(r, 'Tag number')} has the parent {parent}, which is not in the sheet")
        children.setdefault(ids[name_key(parent)] if parent else None, []).append(r)
    nodes: list[dict] = []

    def walk(parent: str | None, depth: int) -> None:  # parents before their children, each level in the file's order
        if depth > 50:
            raise ValueError("Plant Areas: the parent tags make a loop")
        for r in children.get(parent, []):
            me = ids[name_key(_get(r, "Tag number"))]
            nodes.append({"id": me, "parent_id": parent, "tag": _get(r, "Tag number"), "description": _get(r, "Description"),
                          "area_type": _get(r, "Type"), "wbs": _get(r, "WBS number")})
            if me != parent:
                walk(me, depth + 1)
    walk(None, 0)
    if len(nodes) != len(rows):
        raise ValueError("Plant Areas: the parent tags make a loop, or a tag number is used twice")
    return Parsed({"nodes": nodes}, [n["tag"] for n in nodes], labels={n["id"]: n["tag"] for n in nodes})


# -- Equipment Packages ----------------------------------------------------------------------------



def _rows_columns(key: str, columns: dict[str, list[str]] | None = None) -> list[str]:
    """The headers of a list's rows sheet: the project's columns of the list (`columns`;
    default the built-in ones), then its row settings."""
    return list((columns or {}).get(key) or LISTS[key].columns) + list(ROW_SETTINGS.get(key, {}))


#: The Equipment Packages sheet: one row per equipment type, with its package's columns; a package
#: with no equipment types has one row with the equipment type columns blank.
PACKAGES_HEAD = ["Package number", "Package description", "Vendor", "Package type", "Equipment type", "Equipment type description"]


def export_equipment_packages(p: EquipmentPackageList, columns: dict[str, list[str]] | None = None) -> Sheets:
    grid: Grid = [list(PACKAGES_HEAD)]
    for item in p.items:
        package = [item.number, item.description, item.vendor or None, item.package_type]
        types = [t for t in p.types if t.package_id == item.id]
        grid += [package + [t.name, t.description or None] for t in types] or [package + [None, None]]
    out: Sheets = [("Equipment Packages", grid)]
    for key in TEMPLATE_LISTS:  # the rows an equipment type has for a list, one sheet per list
        heads = _rows_columns(key, columns)
        out.append((_rows_sheet(key), [["Equipment type"] + heads] + [
            [t.name] + [row.get(c) or None for c in heads] for t in p.types for row in t.rows.get(key, [])]))
    return out


def import_equipment_packages(sheets: dict[str, Rows], old: EquipmentPackageList,
                              columns: dict[str, list[str]] | None = None) -> Parsed:
    """Reads the Equipment Packages sheet (packages and their equipment types together), or a
    workbook of before, with a Packages sheet and an Equipment types sheet."""
    keep = _keep([(i.id, i.number) for i in old.items])
    notes: list[str] = []
    items: list[dict] = []
    wanted: list[tuple[str, str, str]] | None = []  # (package number, equipment type, its description); None: keep the types
    if "equipment packages" in sheets:
        seen: dict[str, dict] = {}
        differ: set[str] = set()
        for r in _sheet(sheets, "Equipment Packages", ("Package number", "Package description", "Package type", "Equipment type")):
            number = _get(r, "Package number")
            package = {"number": number, "description": _get(r, "Package description"), "vendor": _get(r, "Vendor"),
                       "package_type": _get(r, "Package type")}
            k = name_key(number)
            if k not in seen:  # a package's first row gives its columns
                seen[k] = {"id": keep(number)} | package
                items.append(seen[k])
            elif any(v and v != seen[k][f] for f, v in package.items() if f != "number"):
                differ.add(number)
            if _get(r, "Equipment type"):
                wanted.append((number, _get(r, "Equipment type"), _get(r, "Equipment type description")))
        if differ:
            notes.append("Package(s) with different details on their rows; the first row's are used: " + ", ".join(sorted(differ)))
    else:
        rows = _sheet(sheets, "Packages", ("Number", "Description", "Type"))
        items = [{"id": keep(_get(r, "Number")), "number": _get(r, "Number"), "description": _get(r, "Description"),
                  "vendor": _get(r, "Vendor"), "package_type": _get(r, "Type")} for r in rows]
        if "equipment types" in sheets:
            wanted = [(_get(r, "Package number"), _get(r, "Name"), _get(r, "Description"))
                      for r in _sheet(sheets, "Equipment types", ("Package number", "Name"))]
        else:
            wanted = None

    if wanted is None:
        kept = {i["id"] for i in items}
        types = [t.model_dump() for t in old.types if t.package_id in kept]
        notes.append('No equipment types in the file: they stay as they are.')
    else:
        packages = _Names("Package(s) of an equipment type", [(i["id"], i["number"]) for i in items])
        old_numbers = {i.id: i.number for i in old.items}
        keep_type = _keep([(t.id, f"{old_numbers.get(t.package_id, '')}|{t.name}") for t in old.types])
        before = {t.id: t for t in old.types}
        types = []
        for number, name, description in wanted:
            package = packages.get(number)
            if package:
                tid = keep_type(f"{number}|{name}")
                types.append({"id": tid, "package_id": package, "name": name, "description": description,
                              "rows": {k: [dict(x) for x in v] for k, v in before[tid].rows.items()} if tid in before else {}})
        packages.note(notes, "those equipment types are left out")
        # the types' rows for the deliverable lists: a sheet in the file replaces those rows, a sheet left out keeps them
        by_name = {name_key(t["name"]): t for t in types}
        for key in TEMPLATE_LISTS:
            title = _rows_sheet(key)
            if title.casefold() not in sheets:
                if any(t["rows"].get(key) for t in types):
                    notes.append(f'No "{title}" sheet: those rows stay as they are.')
                continue
            for t in types:
                t["rows"][key] = []
            unknown: set[str] = set()
            for r in _sheet(sheets, title, ("Equipment type",)):
                owner = by_name.get(name_key(_get(r, "Equipment type")))
                if owner is None:
                    unknown.add(_get(r, "Equipment type"))
                    continue
                owner["rows"][key].append({c: _get(r, c) for c in _rows_columns(key, columns) if _get(r, c)})
            if unknown:
                notes.append(f"{title}: rows of equipment type(s) that are not in the file's equipment types are left out: "
                             + ", ".join(sorted(unknown)))
    return Parsed({"items": items, "types": types}, [i["number"] for i in items], notes,
                  {i["id"]: i["number"] for i in items} | {t["id"]: t["name"] for t in types})


# -- Load Types ------------------------------------------------------------------------------------

LOAD_TYPE_HEAD = ["Code", "Name", "Rating unit", "Voltage", "Phases", "From", "To", "STD Drg", "Bucket type", "Load type",
                  "Field options", "Multi load", "Load qty", "PDF"]
_LT_FIELDS = ("code", "name", "rating_unit", "voltage", "phases", "from_value", "to_value", "std_drg", "bucket_type",
              "load_type", "field_options", "multi_load", "load_qty")


def _rows_sheet(key: str) -> str:
    return f"{LISTS[key].deliverable_type} rows".replace("/", "-")


def export_load_types(types: LoadTypeList, columns: dict[str, list[str]] | None = None) -> Sheets:
    out: Sheets = [("Load Types", [LOAD_TYPE_HEAD] + [
        [getattr(t, f) if f != "multi_load" else ("Yes" if t.multi_load else None) for f in _LT_FIELDS]
        + [t.pdf.file_name if t.pdf else None] for t in types.items])]
    for key in TEMPLATE_LISTS:  # the rows each load of the type adds to a list, one sheet per list
        heads = _rows_columns(key, columns)
        out.append((_rows_sheet(key), [["Load type"] + heads] + [
            [t.code] + [row.get(c) or None for c in heads] for t in types.items for row in t.rows.get(key, [])]))
    return out


def import_load_types(sheets: dict[str, Rows], old: LoadTypeList, columns: dict[str, list[str]] | None = None) -> Parsed:
    rows = _sheet(sheets, "Load Types", ("Code", "Name", "Rating unit", "Voltage", "Phases"))
    keep = _keep([(t.id, t.code) for t in old.items])
    before = {t.id: t for t in old.items}
    notes: list[str] = []
    items = []
    for r in rows:
        item = {"id": keep(_get(r, "Code"))} | {f: _get(r, h) for f, h in zip(_LT_FIELDS, LOAD_TYPE_HEAD)}
        item["multi_load"] = "yes" if _yes(item["multi_load"]) else "no"
        item["rows"] = {k: [dict(x) for x in v] for k, v in before[item["id"]].rows.items()} if item["id"] in before else {}
        # component tables aren't in this workbook (they are in a load type's own: export_type_rows)
        item["components"] = [c.model_dump() for c in before[item["id"]].components] if item["id"] in before else []
        items.append(item)
    by_code = {name_key(i["code"]): i for i in items}
    for key in TEMPLATE_LISTS:
        title = _rows_sheet(key)
        if title.casefold() not in sheets:
            notes.append(f'No "{title}" sheet: those rows stay as they are.')
            continue
        heads = _rows_columns(key, columns)
        for i in items:
            i["rows"][key] = []
        unknown: set[str] = set()
        for r in _sheet(sheets, title, ("Load type",)):
            item = by_code.get(name_key(_get(r, "Load type")))
            if item is None:
                unknown.add(_get(r, "Load type"))
                continue
            item["rows"][key].append({c: _get(r, c) for c in heads if _get(r, c)})
        if unknown:
            notes.append(f"{title}: rows of load type(s) not in the Load Types sheet are left out: {', '.join(sorted(unknown))}")
    if any(before[i["id"]].pdf for i in items if i["id"] in before):
        notes.append("Attached PDFs stay with their load types (they are not in the workbook).")
    return Parsed({"items": items}, [i["code"] for i in items], notes, {i["id"]: i["code"] for i in items})


# -- one load type's or equipment type's rows -------------------------------------------------------

def _type_sheet(key: str) -> str:
    return LISTS[key].deliverable_type.replace("/", "-")


TAGS_SHEET = "Tags"


TABLE_SHEET = "Table "  # + the component table's name


def _bounds_heads(field: str) -> list[str]:
    return [f"Min {field}", f"Max {field}"]


def export_type_rows(rows: dict[str, list[dict[str, str]]], columns: dict[str, list[str]] | None = None,
                     tags: list[tuple[str, str]] = (), paths: list[tuple[str, str]] = (),
                     modifiers: list[tuple[str, str]] = (), components: list | None = None) -> Sheets:
    """One type's rows: a sheet per list (the project's columns, then the row settings), every
    list even when it has no rows, and a Tags sheet listing what a cell can use (for reference:
    an import ignores it). `tags`, `paths`, `modifiers`: [(example, what it is)]."""
    out: Sheets = []
    for key in TEMPLATE_LISTS:
        heads = _rows_columns(key, columns)
        out.append((_type_sheet(key), [heads] + [[row.get(c) or None for c in heads] for row in rows.get(key, [])]))
    for t in components or []:  # a load type's component tables: "Min <field>", "Max <field>", then its columns
        out.append((f"{TABLE_SHEET}{t.name}"[:31], [_bounds_heads(t.match_field) + list(t.columns)] + [
            [_num_or_text(r.min), _num_or_text(r.max)] + [r.values.get(c) or None for c in t.columns] for r in t.rows]))
    ref: Grid = [["Tag", "What it is", "Kind"]]
    ref += [[t, m, "the row's tag"] for t, m in tags]
    ref += [[t, m, "linked record (dot notation)"] for t, m in paths]
    ref += [[t, m, "modifier"] for t, m in modifiers]
    out.append((TAGS_SHEET, ref))
    return out


def _num_or_text(v: str | None):
    if v is None:
        return None
    try:
        f = float(v)
        return int(f) if f.is_integer() else f
    except ValueError:
        return v


def read_component_tables(data: bytes, old: list | None = None) -> list[dict] | None:
    """A load type's component tables from its workbook (the "Table <name>" sheets; None when it
    has none): each sheet's first two headings are "Min <field>" and "Max <field>", the rest its
    columns, in order. A table that was there before keeps its id. Raises ValueError."""
    from openpyxl import load_workbook

    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 - any unreadable file
        raise ValueError("this is not an Excel workbook (.xlsx)") from exc
    ids = {re.sub(r"[\s_]+", "", t.name).casefold(): t.id for t in old or []}
    out = []
    for ws in wb.worksheets:
        if not ws.title.casefold().startswith(TABLE_SHEET.casefold()):
            continue
        name = ws.title[len(TABLE_SHEET):].strip()
        rows = ws.iter_rows(values_only=True)
        head = [_text(h) for h in next(rows, ())]
        while head and not head[-1]:
            head.pop()
        if len(head) < 3 or not head[0].casefold().startswith("min") or not head[1].casefold().startswith("max"):
            raise ValueError(f'the "{ws.title}" sheet must start with the columns "Min <field>" and "Max <field>", then the table\'s columns')
        field = head[0][3:].strip() or "load_rating"
        cols = head[2:]
        table_rows = []
        for r in rows:
            cells = [_text(v) for v in r][:len(head)]
            if not any(cells):
                continue
            cells += [""] * (len(head) - len(cells))
            table_rows.append({"min": cells[0], "max": cells[1], "values": {c: v for c, v in zip(cols, cells[2:]) if v}})
        out.append({"id": ids.get(re.sub(r"[\s_]+", "", name).casefold()), "name": name, "match_field": field, "columns": cols,
                    "rows": table_rows})
    return out or None


def import_type_rows(sheets: dict[str, Rows], columns: dict[str, list[str]] | None = None) -> Parsed:
    """A workbook of one type's rows (see export_type_rows): the payload is {list key: rows}
    with only the lists whose sheet is there; a list without a sheet stays as it is (noted).
    Headings are matched ignoring case and spaces; one that is no column of the list is
    refused (ValueError)."""
    def k(h: str) -> str:
        return re.sub(r"\s+", "", h).casefold()

    payload: dict[str, list[dict[str, str]]] = {}
    notes: list[str] = []
    problems: list[str] = []
    for key in TEMPLATE_LISTS:
        title = _type_sheet(key)
        rows = sheets.get(title.casefold())
        if rows is None:
            notes.append(f'No "{title}" sheet: those rows stay as they are.')
            continue
        heads = {k(h): h for h in _rows_columns(key, columns)}
        unknown = sorted({h for r in rows for h in r if h and k(h) not in heads})
        if unknown:
            problems.append(f"{title}: not a column of the {LISTS[key].deliverable_type}: {', '.join(unknown)}")
            continue
        payload[key] = [{heads[k(h)]: v for h, v in r.items() if h and v.strip()} for r in rows]
        payload[key] = [r for r in payload[key] if r]
    if problems:
        raise ValueError("; ".join(problems))
    return Parsed(payload, [], notes)


# -- Equipment Codes, Instrument Codes, Cable Types ------------------------------------------------

CODE_HEADS = {"equipment-codes": (["Code", "Name", "Description", "Disciplines"], "Equipment Codes"),
              "instrument-codes": (["Code", "Name", "Description", "PLC code"], "Instrument Codes")}


def export_code_list(list_id: str, items: list[EquipmentCode] | list[InstrumentCode]) -> Sheets:
    head, title = CODE_HEADS[list_id]
    last = (lambda i: ", ".join(i.disciplines) or None) if list_id == "equipment-codes" else (lambda i: i.plc_code or None)
    return [(title, [head] + [[i.code, i.name, i.description or None, last(i)] for i in items])]


def import_code_list(sheets: dict[str, Rows], list_id: str, old: list, disciplines: dict[str, str] | None = None) -> Parsed:
    """`disciplines`: the project's, code -> name (an equipment code names them by either)."""
    head, title = CODE_HEADS[list_id]
    keep = _keep([(i.id, i.code) for i in old])
    items = []
    for r in _sheet(sheets, title, ("Code", "Name")):
        item: dict[str, object] = {"id": keep(_get(r, "Code")), "code": _get(r, "Code"), "name": _get(r, "Name"),
                                   "description": _get(r, "Description")}
        if list_id == "equipment-codes":
            # a discipline by its letter or its name
            known = DISCIPLINES if disciplines is None else disciplines
            by_name = {name.casefold(): code for code, name in known.items()} | {code.casefold(): code for code in known}
            parts = [p.strip() for p in _get(r, "Disciplines").replace(";", ",").split(",") if p.strip()]
            item["disciplines"] = [by_name.get(p.casefold(), p) for p in parts]
        else:
            item["plc_code"] = _get(r, "PLC code")
        items.append(item)
    return Parsed({"items": items}, [str(i["code"]) for i in items], labels={str(i["id"]): str(i["code"]) for i in items})


CABLE_HEAD = ["Code", "Application", "Type", "Cores", "Diameter", "Voltage", "Insulation", "Description", "Sort"]


def export_cable_types(items: list[CableType]) -> Sheets:
    return [("Cable Types", [CABLE_HEAD] + [[getattr(c, h.casefold()) if getattr(c, h.casefold()) != "" else None
                                             for h in CABLE_HEAD] for c in items])]


def import_cable_types(sheets: dict[str, Rows], old: list[CableType]) -> Parsed:
    keep = _keep([(c.id, c.code) for c in old])
    items = [{"id": keep(_get(r, "Code"))} | {h.casefold(): _get(r, h) for h in CABLE_HEAD}
             for r in _sheet(sheets, "Cable Types", ("Code",))]
    return Parsed({"items": items}, [i["code"] for i in items], labels={i["id"]: i["code"] for i in items})


# -- the Electrical Equipment List -----------------------------------------------------------------

EEL_HEAD = ["Tag", "Description", "Equipment code", "Plant area", "Vendor package", "Load type", "Rating", "Units", "Voltage",
            "Phases", "Distribution panel", "Supplied from", "Manufacturer", "Model number", "Supplied by", "Installed by",
            "Terminated by"]


@dataclass
class EelNames:
    """What the Electrical Equipment List refers to, as (id, name) pairs."""
    equipment_codes: list[tuple[str, str]]
    plant_areas: list[tuple[str, str]]
    packages: list[tuple[str, str]]
    load_types: list[tuple[str, str]]
    import_panels: list[tuple[str, str]]  # the imports' distribution panels: (Load List ref, tag)


def export_eel(eel: EelList, names: EelNames) -> Sheets:
    code, area, package, load = (dict(x) for x in (names.equipment_codes, names.plant_areas, names.packages, names.load_types))
    supply = dict(names.import_panels) | {f"{EEL_SOURCE}/{i.id}": i.tag for i in eel.items} | {PRIMARY_SUPPLY: PRIMARY}
    return [("Electrical Equipment", [EEL_HEAD] + [[
        i.tag, i.description, code.get(i.equipment_code_id), area.get(i.plant_area_id), package.get(i.vendor_package_id or ""),
        load.get(i.load_type_id or ""), float(i.rating) if i.rating is not None else None, i.rating_unit, i.voltage, i.phases,
        "Yes" if i.is_panel else None, supply.get(i.supplied_from or ""), i.manufacturer or None, i.model_number or None,
        package.get(i.supplied_by_id or ""), package.get(i.installed_by_id or ""), package.get(i.terminated_by_id or "")]
        for i in eel.items])]


def import_eel(sheets: dict[str, Rows], old: EelList, names: EelNames) -> Parsed:
    rows = _sheet(sheets, "Electrical Equipment", ("Tag", "Description", "Equipment code", "Plant area"))
    keep = _keep([(i.id, i.tag) for i in old.items])
    ids = [keep(_get(r, "Tag")) for r in rows]
    codes = _Names("Equipment code(s)", names.equipment_codes)
    areas = _Names("Plant area(s)", names.plant_areas)
    packages = _Names("Package(s)", names.packages)
    loads = _Names("Load type(s)", names.load_types)
    supplies = _Names("Supplied-from panel(s)", names.import_panels + [(f"{EEL_SOURCE}/{i}", _get(r, "Tag")) for i, r in zip(ids, rows)]
                      + [(PRIMARY_SUPPLY, PRIMARY), (PRIMARY_SUPPLY, "Primary")])
    items = [{
        "id": i, "tag": _get(r, "Tag"), "description": _get(r, "Description"), "equipment_code_id": codes.get(_get(r, "Equipment code")),
        "plant_area_id": areas.get(_get(r, "Plant area")), "vendor_package_id": packages.get(_get(r, "Vendor package")),
        "load_type_id": loads.get(_get(r, "Load type")), "rating": _get(r, "Rating"), "rating_unit": _get(r, "Units") or None,
        "voltage": _get(r, "Voltage"), "phases": _get(r, "Phases") or None, "is_panel": _yes(_get(r, "Distribution panel")),
        "supplied_from": supplies.get(_get(r, "Supplied from")), "manufacturer": _get(r, "Manufacturer"),
        "model_number": _get(r, "Model number"), "supplied_by_id": packages.get(_get(r, "Supplied by")),
        "installed_by_id": packages.get(_get(r, "Installed by")), "terminated_by_id": packages.get(_get(r, "Terminated by")),
    } for i, r in zip(ids, rows)]
    notes: list[str] = []
    for n in (codes, areas, packages, loads, supplies):
        n.note(notes)
    return Parsed({"items": items}, [i["tag"] for i in items], notes, {i["id"]: i["tag"] for i in items})


# -- the Load List ---------------------------------------------------------------------------------

LOADLIST_HEAD = ["Source", "Key", "Tag", "Description", "Status", "Plant area", "Load type", "Distribution panel",
                 "Supplied from", "Cable length (m)", "Power cable", "Parallel cables", "Cable insulation", "Cable size",
                 "Earth size"]


def export_load_list(rows: list[LoadListRow], areas: dict[str, str], types: dict[str, str], fields: list[str],
                     labels: dict[str, str] | None = None) -> Sheets:
    """`areas`: plant area id -> tag; `types`: load type id -> code; `fields`: the mapped
    load-list fields to add after the editable columns (for reference: an import ignores them),
    headed by their `labels` (the project's names for them; default the keys)."""
    tags = {r.ref(): r.tag() for r in rows} | {PRIMARY_SUPPLY: PRIMARY}
    extra = [f for f in fields if f not in ("tag", "desc")]
    fixed = {h.casefold() for h in LOADLIST_HEAD}
    heads = [(labels or {}).get(f, f) for f in extra]
    heads = [h + " (import)" if h.casefold() in fixed else h for h in heads]
    grid: Grid = [LOADLIST_HEAD + heads]
    for r in sorted(rows, key=lambda x: (x.status != "active", x.source.casefold(), x.tag().casefold())):
        grid.append([r.source, r.key, r.tag(), r.values.get("desc"), "Active" if r.status == "active" else "Deleted",
                     areas.get(r.plant_area_id or ""), types.get(r.load_type_id or ""), "Yes" if r.is_panel else None,
                     tags.get(r.supplied_from or ""), r.cable_length, r.cable_construction, r.cable_parallel,
                     r.cable_insulation or None, r.cable_size or None, r.earth_size or None]
                    + [r.values.get(f) for f in extra])
    return [("Load List", grid)]


def import_load_list(sheets: dict[str, Rows], rows: list[LoadListRow], areas: list[tuple[str, str]],
                     types: list[tuple[str, str]]) -> Parsed:
    """The payload is a list of (row, change): what each row of the file changes in the Load
    List row with the same Source and Key (only what differs). The rows themselves come from
    the imports, so a file row with no match is skipped, and nothing is added or removed."""
    file = _sheet(sheets, "Load List", ("Source", "Key"))
    by_key = {(name_key(r.source), r.key.strip()): r for r in rows}
    area_names, type_names = _Names("Plant area(s)", areas), _Names("Load type(s)", types)
    panels = _Names("Supplied-from panel(s)", [(r.ref(), r.tag()) for r in rows if r.status == "active"]
                    + [(PRIMARY_SUPPLY, PRIMARY), (PRIMARY_SUPPLY, "Primary")])
    notes: list[str] = []
    changes: list[tuple[LoadListRow, dict[str, object]]] = []
    unmatched = 0

    def number(text: str, kind, what: str, tag: str):
        if not text:
            return None
        try:
            return kind(float(text))
        except ValueError:
            raise ValueError(f"Load List: {tag}: {what} '{text}' is not a number") from None

    for f in file:
        row = by_key.get((name_key(_get(f, "Source")), _get(f, "Key")))
        if row is None:
            unmatched += 1
            continue
        construction = next((c for c in CABLE_CONSTRUCTIONS if name_key(c) == name_key(_get(f, "Power cable"))), None)
        if _get(f, "Power cable") and construction is None:
            raise ValueError(f"Load List: {row.tag()}: the power cable is Multicore or Single core")
        want: dict[str, object] = {
            "cable_length": number(_get(f, "Cable length (m)"), float, "cable length", row.tag()),
            "cable_construction": construction,
            "cable_parallel": number(_get(f, "Parallel cables"), int, "parallel cables", row.tag()),
            "cable_insulation": _get(f, "Cable insulation"), "cable_size": _get(f, "Cable size"), "earth_size": _get(f, "Earth size")}
        if row.recipe_id != EEL_SOURCE:  # the Electrical Equipment List sets its own rows' allocations
            want |= {"plant_area_id": area_names.get(_get(f, "Plant area")), "load_type_id": type_names.get(_get(f, "Load type")),
                     "is_panel": _yes(_get(f, "Distribution panel")), "supplied_from": panels.get(_get(f, "Supplied from"))}
        change = {k: v for k, v in want.items() if k in f_columns(f, k) and getattr(row, k) != v}
        if change:
            changes.append((row, change))
    if unmatched:
        notes.append(f"{unmatched} row(s) of the file are not in the Load List (by Source and Key) and are skipped.")
    for n in (area_names, type_names, panels):
        n.note(notes, "set to blank")
    return Parsed(changes, [r.tag() for r, _ in changes], notes)


_LL_COLUMN = {"plant_area_id": "Plant area", "load_type_id": "Load type", "is_panel": "Distribution panel",
              "supplied_from": "Supplied from", "cable_length": "Cable length (m)", "cable_construction": "Power cable",
              "cable_parallel": "Parallel cables", "cable_insulation": "Cable insulation", "cable_size": "Cable size",
              "earth_size": "Earth size"}


def f_columns(file_row: dict[str, str], field_name: str) -> tuple[str, ...]:
    """(field,) when the file has the field's column: a column left out of the file changes nothing."""
    return (field_name,) if _LL_COLUMN[field_name].casefold() in file_row else ()


# -- Distribution Panels ---------------------------------------------------------------------------

PANEL_HEAD = ["Panel", "Load List panel", "Title", "Type", "View", "Ways", "Single phase voltage", "Power factor",
              "Isolator & chassis rating (A)", "Upstream CB size (A)"]
CIRCUIT_HEAD = ["Panel", "Circuit", "Way", "Phase", "Poles", "What", "Load tag", "Description", "Load type", "Qty",
                "Watts (Ea.)", "CB rating (A)"]
HEADING_HEAD = ["Panel", "Above way", "Text"]
_KINDS = {"load": "Load", "spare_cb": "Spare CB", "rcd": "RCD RTS", "light_control": "Light Control CCT", "other": "Other"}
_PHASE = {"R": "Red", "W": "White", "B": "Blue"}


def export_distribution_panels(doc: DistributionPanelList, loads: dict[str, LoadListRow]) -> Sheets:
    """`loads`: the Load List rows by ref. A circuit has one row per pole; its description and
    load type are only what was typed on the panel (blank: the load's own)."""
    tag = lambda ref: loads[ref].tag() if ref in loads else None  # noqa: E731
    panels: Grid = [PANEL_HEAD]
    circuits: Grid = [CIRCUIT_HEAD]
    headings: Grid = [HEADING_HEAD]
    for p in doc.panels:
        panels.append([p.tag, tag(p.load_ref or ""), p.title or None, "Three-phase" if p.phase_type == "three-phase" else "Single-phase",
                       "Single line diagram" if p.view == "sld" else "Switchboard", p.ways, p.voltage, p.power_factor,
                       p.isolator_rating, p.upstream_cb])
        for e in sorted(p.entries, key=lambda x: (x.way, POLES.index(x.pole) if x.pole else 0)):
            poles = list(POLES) if e.poles == 3 else [e.pole or ""]
            for pole, v in zip(poles, e.rows):
                circuits.append([p.tag, circuit_name(e.way, pole), e.way, _PHASE.get(pole), e.poles, _KINDS[e.kind],
                                 tag(e.load_ref or ""), e.description or None, e.load_type or None, v.qty, v.watts_each, v.cb_rating])
        headings += [[p.tag, d.before_way, d.label] for d in sorted(p.dividers, key=lambda x: x.before_way)]
    return [("Panels", panels), ("Circuits", circuits), ("Headings", headings)]


def import_distribution_panels(sheets: dict[str, Rows], old: DistributionPanelList, loads: dict[str, LoadListRow]) -> Parsed:
    def number(text: str, what: str, where: str, default: float | None = None) -> float | None:
        if not text:
            return default
        try:
            return float(text)
        except ValueError:
            raise ValueError(f"{where}: {what} '{text}' is not a number") from None

    keep = _keep([(p.id, p.tag) for p in old.panels])
    active = ordered(list(loads.values()))
    load_panels = _Names("Load List panel(s)", [(r.ref(), r.tag()) for r in active if r.is_panel])
    notes: list[str] = []
    panels: dict[str, DistributionPanel] = {}
    for r in _sheet(sheets, "Panels", ("Panel",)):
        name = _get(r, "Panel")
        where = f"Panels: {name}"
        defaults = DistributionPanel()
        panels[name_key(name)] = DistributionPanel(
            id=keep(name), tag=name, load_ref=load_panels.get(_get(r, "Load List panel")), title=_get(r, "Title"),
            phase_type="single-phase" if _get(r, "Type").casefold().startswith("single") else "three-phase",
            view="sld" if "line" in _get(r, "View").casefold() or _get(r, "View").casefold() == "sld" else "switchboard",
            ways=int(number(_get(r, "Ways"), "ways", where, defaults.ways) or 0),
            voltage=number(_get(r, "Single phase voltage"), "voltage", where, defaults.voltage) or 0,
            power_factor=number(_get(r, "Power factor"), "power factor", where, defaults.power_factor) or 0,
            isolator_rating=number(_get(r, "Isolator & chassis rating (A)"), "rating", where, defaults.isolator_rating) or 0,
            upstream_cb=number(_get(r, "Upstream CB size (A)"), "size", where, defaults.upstream_cb) or 0)
    load_panels.note(notes, "those panels are not linked")
    kinds = {name_key(v): k for k, v in _KINDS.items()} | {name_key(v): k for k, v in KIND_LABELS.items() if v}
    phases = {"red": "R", "white": "W", "blue": "B", "r": "R", "w": "W", "b": "B"}
    unknown_loads: set[str] = set()
    if "circuits" in sheets:
        entries: dict[tuple[str, int, str], PanelEntry] = {}
        for r in _sheet(sheets, "Circuits", ("Panel", "Way")):
            panel = panels.get(name_key(_get(r, "Panel")))
            where = f"Circuits: {_get(r, 'Panel')} way {_get(r, 'Way')}"
            if panel is None:
                raise ValueError(f"{where}: the panel is not in the Panels sheet")
            way = int(number(_get(r, "Way"), "way", where) or 0)
            three = panel.phase_type == "three-phase"
            pole = phases.get(_get(r, "Phase").casefold()) if three else None
            if three and pole is None:
                raise ValueError(f"{where}: the phase is Red, White or Blue")
            poles = 3 if three and _get(r, "Poles") == "3" else 1
            values = PoleValues(cb_rating=number(_get(r, "CB rating (A)"), "CB rating", where),
                                qty=(lambda q: None if q is None else int(q))(number(_get(r, "Qty"), "quantity", where)),
                                watts_each=number(_get(r, "Watts (Ea.)"), "watts", where))
            key = (panel.id, way, "" if poles == 3 else pole or "")
            entry = entries.get(key)
            if entry is None:
                kind = kinds.get(name_key(_get(r, "What")), "load" if _get(r, "Load tag") else "other")
                ref = None
                if kind == "load":
                    tag = _get(r, "Load tag")
                    fed = [x for x in active if name_key(x.tag()) == name_key(tag)]
                    mine = [x for x in fed if x.supplied_from == panel.load_ref]
                    ref = (mine or fed or [None])[0]
                    if ref is None:
                        unknown_loads.add(tag or "(blank)")
                        continue
                    ref = ref.ref()
                entry = entries[key] = PanelEntry(way=way, pole="R" if poles == 3 else pole, poles=poles, kind=kind, load_ref=ref,  # type: ignore[arg-type]
                                                  description=_get(r, "Description"), load_type=_get(r, "Load type"),
                                                  rows=[PoleValues() for _ in range(poles)])
                panel.entries.append(entry)
            entry.rows[POLES.index(pole) if poles == 3 and pole else 0] = values
    else:
        notes.append('No "Circuits" sheet: the panels have no circuits.')
    if unknown_loads:
        notes.append(f"Load(s) not in the Load List, left off the panels: {', '.join(sorted(unknown_loads)[:12])}")
    for r in sheets.get("headings", []):
        panel = panels.get(name_key(_get(r, "Panel")))
        if panel is not None and _get(r, "Text"):
            panel.dividers.append(PanelDivider(before_way=int(number(_get(r, "Above way"), "way", "Headings") or 0), label=_get(r, "Text")))
    doc = DistributionPanelList(panels=list(panels.values()))
    labels = {p.id: p.tag for p in doc.panels} | {e.id: f"{p.tag} {circuit_name(e.way, e.pole or '')}" for p in doc.panels for e in p.entries}
    labels |= {d.id: f"{p.tag} heading above way {d.before_way}" for p in doc.panels for d in p.dividers}
    return Parsed(doc, [p.tag for p in doc.panels], notes, labels)


# -- the Instrument Runsheet and the MEL -----------------------------------------------------------

def export_instrument_runsheet(rows: list) -> Sheets:
    """`rows`: the runsheet as typed (instrument_runsheet.TypedRow). Numbers are written as text,
    exactly as they were typed (a leading zero stays)."""
    from .instrument_runsheet import FIXED, headings

    numbers = max([0] + [len(r.cells) - len(FIXED) for r in rows])  # as many number columns as the rows have (35 or more)
    return [("Instrument Runsheet", [headings(numbers)] + [[c if c != "" else None for c in r.cells] for r in rows])]


def import_instrument_runsheet(sheets: dict[str, Rows]) -> Parsed:
    """The payload is the rows as typed; the engine resolves and checks their references."""
    from .instrument_runsheet import HEADINGS, MAX_NUMBERS, TypedRow, headings

    file = _sheet(sheets, "Instrument Runsheet", tuple(HEADINGS[:3]))
    # the file's number columns: #1, #2, ... up to the highest it has (it can have more than 35)
    found = [int(h[1:]) for h in (file[0] if file else {}) if h.startswith("#") and h[1:].isdigit()]
    heads = headings(min(max(found, default=0), MAX_NUMBERS + 1))
    rows = [TypedRow(cells=[_get(r, h) for h in heads]) for r in file]
    return Parsed(rows, [], labels={r.id: f"Row {n}" for n, r in enumerate(rows, start=1)})


def export_mel(headers: list[str], rows: list) -> Sheets:
    """`rows`: the MEL's rows (source, tag, in_load_list, values). For reading: it is not imported."""
    grid: Grid = [["Source", "Tag", "In the Load List"] + headers]
    grid += [[r.source, r.tag, "Yes" if r.in_load_list else "No"] + [r.values.get(h) or None for h in headers] for r in rows]
    return [("MEL", grid)]


# -- the Drawing List and the Document List ---------------------------------------------------------

def export_register(spec, rows: list[dict]) -> Sheets:
    """`spec`: drawing_list.DRAWINGS or DOCUMENTS; `rows`: the items as text (field -> value).
    The issue date is written as dd/mm/yyyy."""
    return [(spec.name, [list(spec.headings)] + [[r.get(f) or None for f in spec.fields] for r in rows])]


def import_register(sheets: dict[str, Rows], spec, old: list) -> Parsed:
    """The payload is the items as typed (field -> text); the engine checks them, resolving each
    discipline, type and status against the project's Enums. An item keeps the identity of the
    one with the same number. `old`: the items as they are."""
    file = _sheet(sheets, spec.name, (spec.headings[0],))
    keep = _keep([(d.id, d.number) for d in old])
    rows = [{"id": keep(_get(r, spec.headings[0]))} | {f: _get(r, h) for f, h in zip(spec.fields, spec.headings)} for r in file]
    return Parsed({"items": rows}, [r["number"] for r in rows],
                  labels={r["id"]: r["number"] or f"A {spec.item} with no number" for r in rows})
