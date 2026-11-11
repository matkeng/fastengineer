# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Rules for the project's key lists."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace

from ..refdata.models import ColumnDef, RefValidationError, new_id
from ..refdata.validate import FALSE, TRUE, coerce, name_key
from pydantic import BaseModel, ValidationError

from .models import (
    DISCIPLINES,
    PHASES,
    RATING_UNITS,
    EelItem,
    EelList,
    EquipmentPackageList,
    LoadType,
    LoadTypeList,
    PlantArea,
    PlantAreaList,
)

#: (field, what it is called, required). Each is unique in its list when filled in.
_AREA_FIELDS = (("tag", "Tag number", True), ("description", "Description", True), ("wbs", "WBS number", False))
_PACKAGE_FIELDS = (("number", "Package number", True), ("description", "Description", True))
_TYPE_FIELDS = (("name", "Name", True),)
_LOAD_FIELDS = (("code", "Code", True), ("name", "Name", True))
_LOAD_TEXT = ("code", "name", "std_drg", "bucket_type", "load_type", "field_options")
_INTEGER = ColumnDef(name="", type="integer")
_DECIMAL = ColumnDef(name="", type="decimal")


def _check_unique(items: list, fields: tuple, errors: dict[str, str]) -> None:
    """Required fields must be filled in; no value is used twice (ignoring case and extra spaces)."""
    for field, label, required in fields:
        seen: set[str] = set()
        for item in items:
            value = getattr(item, field)
            if not value:
                if required:
                    errors[f"{item.id}.{field}"] = f"{label} is required"
            elif name_key(value) in seen:
                errors[f"{item.id}.{field}"] = f"{label} '{value}' is used twice"
            else:
                seen.add(name_key(value))


def check_plant_areas(areas: PlantAreaList) -> PlantAreaList:
    """Tag numbers and descriptions are required and unique in the whole list; WBS numbers
    are optional but unique when filled in (all ignoring case and extra spaces). Parents
    must exist and there must be no cycles. Any area type may sit under any other.
    Returns the items ordered parents-first (depth-first), keeping sibling order."""
    errors: dict[str, str] = {}
    nodes: list[PlantArea] = []
    ids: set[str] = set()
    for n in areas.nodes:
        n = n.model_copy(update={"wbs": n.wbs.strip(), "tag": n.tag.strip(), "description": n.description.strip(),
                                 "parent_id": n.parent_id or None})
        if n.id in ids:
            raise RefValidationError("Two plant areas have the same id.", {f"{n.id}.tag": "Duplicate item"})
        ids.add(n.id)
        nodes.append(n)
    by_id = {n.id: n for n in nodes}

    _check_unique(nodes, _AREA_FIELDS, errors)

    for n in nodes:
        if n.parent_id is not None and n.parent_id not in by_id:
            errors[f"{n.id}.parent"] = "Its parent is not in the list"
    # Cycles: walking up from any item must reach the top.
    for n in nodes:
        seen_ids = {n.id}
        p = n.parent_id
        while p is not None and p in by_id:
            if p in seen_ids:
                errors[f"{n.id}.parent"] = "An item can't be inside itself"
                break
            seen_ids.add(p)
            p = by_id[p].parent_id
    if errors:
        raise RefValidationError(f"{len(errors)} problem(s) in the plant areas.", errors)

    children: dict[str | None, list[PlantArea]] = {}
    for n in nodes:
        children.setdefault(n.parent_id, []).append(n)
    ordered: list[PlantArea] = []

    def walk(parent: str | None) -> None:
        for c in children.get(parent, []):
            ordered.append(c)
            walk(c.id)
    walk(None)
    return areas.model_copy(update={"nodes": ordered})


def plant_area_depth(areas: PlantAreaList) -> int:
    by_id = {n.id: n for n in areas.nodes}
    best = 0
    for n in areas.nodes:
        d, p = 1, n.parent_id
        while p is not None and p in by_id and d <= len(by_id):
            d, p = d + 1, by_id[p].parent_id
        best = max(best, d)
    return best


def check_equipment_packages(packages: EquipmentPackageList, columns: dict[str, list[str]] | None = None) -> EquipmentPackageList:
    """Package numbers and descriptions are required and unique in the list (ignoring case
    and extra spaces). The vendor name is optional and may repeat. Row order is kept.

    Equipment types: the name is required and unique across all types; each belongs to a
    package of the list, so a package can't be removed while it has types. A type's predefined
    rows for the deliverable lists follow the same rules as a load type's. Returns the
    types grouped by package, in package order, keeping their order within a package.
    `columns`: the project's master list columns (default: the built-in ones)."""
    errors: dict[str, str] = {}
    items = []
    ids: set[str] = set()
    for it in packages.items:
        it = it.model_copy(update={"number": it.number.strip(), "description": it.description.strip(),
                                   "vendor": it.vendor.strip()})
        if it.id in ids:
            raise RefValidationError("Two equipment packages have the same id.", {f"{it.id}.number": "Duplicate item"})
        ids.add(it.id)
        items.append(it)
    _check_unique(items, _PACKAGE_FIELDS, errors)

    types = []
    type_ids: set[str] = set()
    for t in packages.types:
        t = t.model_copy(update={"name": t.name.strip(), "description": t.description.strip(),
                                 "rows": _template_rows(t.rows, t.id, errors, "equipment types", columns)})
        if t.id in type_ids:
            raise RefValidationError("Two equipment types have the same id.", {f"{t.id}.name": "Duplicate item"})
        type_ids.add(t.id)
        types.append(t)
        if t.package_id not in ids:
            errors[f"{t.id}.package"] = "Its package is not in the list"
    _check_unique(types, _TYPE_FIELDS, errors)
    if errors:
        raise RefValidationError(f"{len(errors)} problem(s) in the equipment packages.", errors)
    order = {it.id: i for i, it in enumerate(items)}
    types.sort(key=lambda t: order[t.package_id])  # stable: keeps the order within a package
    return packages.model_copy(update={"items": items, "types": types})


def _template_rows(raw: object, rid: str, errors: dict[str, str], owners: str = "load types",
                   columns: dict[str, list[str]] | None = None) -> dict[str, list[dict[str, str]]]:
    """The predefined rows per deliverable list of a load type (or an equipment type, which has
    the same): known lists and columns only, text trimmed, blank cells and wholly blank rows
    dropped. `owners`: what has the rows, for the messages; `columns`: the project's columns
    of each list (default: the built-in ones)."""
    from .loadgen import LISTS, ROW_SETTINGS, TEMPLATE_LISTS

    out: dict[str, list[dict[str, str]]] = {}
    if not isinstance(raw, dict):
        return out
    for key, rows in raw.items():
        if key not in TEMPLATE_LISTS:
            errors[f"{rid}.rows"] = f"'{key}' is not a list that {owners} have rows for"
            continue
        kept = []
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            settings = ROW_SETTINGS.get(key, {})
            known = (columns or {}).get(key) or LISTS[key].columns
            unknown = [c for c in row if c not in known and c not in settings]
            if unknown:
                errors[f"{rid}.rows.{key}"] = f"Not a column of the {LISTS[key].deliverable_type}: {', '.join(unknown)}"
            cells = {c: str(v).strip() for c, v in row.items()
                     if (c in known or c in settings) and v is not None and str(v).strip()}
            for name, allowed in settings.items():
                if name in cells:
                    match = next((a for a in allowed if a.casefold() == cells[name].casefold()), None)
                    if match is None:
                        errors[f"{rid}.rows.{key}"] = f"{name} is blank or one of: {', '.join(allowed)}"
                    else:
                        cells[name] = match
            if any(c in known for c in cells):
                kept.append(cells)
        if kept:
            out[key] = kept
    return out


#: What a component table can't be called: the load type's own fields (<<LoadType.Code>>…).
_LOAD_TYPE_TAGS = {"code", "name", "ratingunit", "voltage", "phases", "from", "to", "stddrg", "buckettype", "loadtype",
                   "fieldoptions", "multiload", "loadqty"}
_TABLE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_ ]{0,24}$")  # 25 at most: a workbook sheet is "Table <name>"


def _components(raw: object, rid: str, errors: dict[str, str]) -> list:
    """A load type's component tables as typed in: a name (letters, digits, _ and spaces, starting
    with a letter; unique in the type, ignoring case, spaces and _; not one of the load type's own
    tag names), the field rows are matched on, value columns (named, unique, not Min or Max), and
    rows whose Min and Max are numbers or blank, Min not above Max, and whose values are in the
    columns. Wholly blank rows are dropped."""
    from .models import ComponentRow, ComponentTable

    def norm(s: str) -> str:
        return re.sub(r"[\s_]+", "", s).casefold()

    out = []
    seen: set[str] = set()
    for n, t in enumerate(raw if isinstance(raw, list) else []):
        if not isinstance(t, dict):
            continue
        where = f"{rid}.components.{n}"
        name = " ".join(str(t.get("name") or "").split())
        if not _TABLE_NAME.match(name):
            errors[f"{where}.name"] = "A table needs a name of up to 25 letters, digits, spaces or _, starting with a letter"
        elif norm(name) in _LOAD_TYPE_TAGS:
            errors[f"{where}.name"] = f"'{name}' is a load type field's tag: choose another name"
        elif norm(name) in seen:
            errors[f"{where}.name"] = f"Two tables are called {name}"
        seen.add(norm(name))
        field = str(t.get("match_field") or "").strip() or "load_rating"
        columns: list[str] = []
        for c in t.get("columns") or []:
            c = " ".join(str(c).split())
            if not c:
                continue
            if norm(c) in ("min", "max"):
                errors[f"{where}.columns"] = f"'{c}' is taken: Min and Max are the range of each row"
            elif norm(c) in {norm(x) for x in columns}:
                errors[f"{where}.columns"] = f"Column '{c}' is in the table twice"
            columns.append(c)
        if not columns:
            errors[f"{where}.columns"] = "A table needs at least one column (e.g. Part Number)"
        rows = []
        for i, r in enumerate(t.get("rows") or []):
            if not isinstance(r, dict):
                continue
            bounds = []
            for b in ("min", "max"):
                text = str(r.get(b) if r.get(b) is not None else "").strip()
                try:
                    bounds.append(str(Decimal(text).normalize()) if text else None)
                    if text and not Decimal(text).is_finite():
                        raise InvalidOperation
                except (InvalidOperation, ValueError):
                    errors[f"{where}.rows.{i}"] = f"Row {i + 1}: {b.title()} must be a number or blank"
                    bounds.append(None)
            values = {str(k): str(v).strip() for k, v in (r.get("values") or {}).items() if v is not None and str(v).strip()}
            unknown = [k for k in values if k not in columns]
            if unknown:
                errors[f"{where}.rows.{i}"] = f"Row {i + 1}: not a column of the table: {', '.join(unknown)}"
            if bounds[0] is not None and bounds[1] is not None and Decimal(bounds[0]) > Decimal(bounds[1]):
                errors[f"{where}.rows.{i}"] = f"Row {i + 1}: Min is more than Max"
            if bounds[0] is None and bounds[1] is None and not values:
                continue
            rows.append(ComponentRow(min=bounds[0], max=bounds[1], values=values))
        out.append(ComponentTable(id=str(t.get("id") or new_id()), name=name, match_field=field, columns=columns, rows=rows))
    return out


def check_load_types(rows: list[dict], columns: dict[str, list[str]] | None = None) -> LoadTypeList:
    """Check the rows of the Load Types list as they were typed in (numbers may be text).

    Code and name are required and unique (ignoring case and extra spaces); kW or Amps,
    voltage and phases are required; voltage and load quantity are whole numbers, not
    negative; the from and to values are numbers and from must not exceed to. Row order
    is kept."""
    errors: dict[str, str] = {}
    out: list[SimpleNamespace] = []
    ids: set[str] = set()
    for raw in rows:
        r = SimpleNamespace(id=str(raw.get("id") or new_id()))
        if r.id in ids:
            raise RefValidationError("Two load types have the same id.", {f"{r.id}.code": "Duplicate item"})
        ids.add(r.id)

        def problem(field: str, message: str) -> None:
            errors[f"{r.id}.{field}"] = message

        def number(field: str, col: ColumnDef):
            try:
                return coerce(raw.get(field), col, None)
            except ValueError as exc:
                problem(field, str(exc))
                return None

        for field in _LOAD_TEXT:
            setattr(r, field, str(raw.get(field) or "").strip())
        r.rating_unit, r.phases = raw.get("rating_unit"), raw.get("phases")
        if r.rating_unit not in RATING_UNITS:
            problem("rating_unit", "Choose kW or Amps")
        if r.phases not in PHASES:
            problem("phases", "Choose the phases")
        for field, label, required in (("voltage", "Voltage", True), ("load_qty", "Load qty", False)):
            value = number(field, _INTEGER)
            setattr(r, field, value)
            if value is None and required and f"{r.id}.{field}" not in errors:
                problem(field, f"{label} is required")
            elif value is not None and value < 0:
                problem(field, "Can't be negative")
        r.from_value, r.to_value = number("from_value", _DECIMAL), number("to_value", _DECIMAL)
        if r.from_value is not None and r.to_value is not None and Decimal(r.from_value) > Decimal(r.to_value):
            problem("to_value", "Must not be less than the From value")
        flag = raw.get("multi_load")
        text = str(flag if flag is not None else "").strip().casefold()
        if text not in TRUE and text not in FALSE:
            problem("multi_load", "Not yes/no")
        r.multi_load = text in TRUE
        r.rows = _template_rows(raw.get("rows"), r.id, errors, columns=columns)
        r.components = _components(raw.get("components"), r.id, errors)
        out.append(r)
    _check_unique(out, _LOAD_FIELDS, errors)
    if errors:
        raise RefValidationError(f"{len(errors)} problem(s) in the load types.", errors)
    return LoadTypeList(items=[LoadType(**vars(r)) for r in out])


# -- equipment codes and instrument codes -------------------------------------------------

_CODE_FIELDS = (("code", "Code", True), ("name", "Name", True))


def check_code_list(rows: list[dict], model: type[BaseModel], what: str, disciplines: dict[str, str] | None = None) -> list:
    """Check the rows of a code list (Equipment Codes, Instrument Codes) as sent by a client.

    Code and name are required and unique (ignoring case and extra spaces); text is trimmed;
    disciplines (when the list has them) must be known codes and are kept once each, in the
    usual order. Returns `model` items in the order given."""
    errors: dict[str, str] = {}
    items: list = []
    ids: set[str] = set()
    for raw in rows:
        rid = str(raw.get("id") or new_id())
        if rid in ids:
            raise RefValidationError(f"Two {what} have the same id.", {f"{rid}.code": "Duplicate item"})
        ids.add(rid)
        data: dict[str, object] = {"id": rid}
        for field, info in model.model_fields.items():
            if field == "id" or info.annotation is not str:
                continue
            value = raw.get(field)
            data[field] = "" if value is None else str(value).strip()
        if "disciplines" in model.model_fields:
            chosen = raw.get("disciplines") or []
            chosen = chosen if isinstance(chosen, list) else [chosen]
            known = DISCIPLINES if disciplines is None else disciplines  # the project's Disciplines enum: code -> name
            unknown = [str(d) for d in chosen if d not in known]
            if unknown:
                errors[f"{rid}.disciplines"] = f"Not a discipline: {', '.join(unknown)}"
            data["disciplines"] = [d for d in known if d in chosen]
        try:
            items.append(model.model_validate(data))
        except ValidationError as exc:
            errors[f"{rid}.{exc.errors()[0]['loc'][0]}"] = "Not valid"
    _check_unique(items, _CODE_FIELDS, errors)
    if errors:
        raise RefValidationError(f"{len(errors)} problem(s) in the {what}.", errors)
    return items


# -- the Electrical Equipment List ----------------------------------------------------------

#: Reference fields -> (what it is called, required).
EEL_REFS = {
    "equipment_code_id": ("Equipment type", True), "plant_area_id": ("Plant area", True),
    "vendor_package_id": ("Vendor package", False), "load_type_id": ("Load type", False),
    "supplied_by_id": ("Supplied by", False), "installed_by_id": ("Installed by", False),
    "terminated_by_id": ("Terminated by", False), "supplied_from": ("Supplied from", False),
}
_EEL_TEXT = ("tag", "description", "manufacturer", "model_number")


def check_eel(rows: list[dict], known: dict[str, set[str]]) -> EelList:
    """Check the items of the Electrical Equipment List as sent (numbers may be text).

    The tag is required and unique in the list; description, equipment type and plant area
    are required; each reference must be one of `known[field]` (`supplied_from`: the primary
    supply or a distribution panel); an item can't be supplied from itself. Rating is a
    number, voltage a whole number (not negative). Order is kept. (Tags must also not repeat
    an import's tags: the engine checks that, as it knows the imports.)"""
    from .loadlist import EEL_SOURCE, PRIMARY_SUPPLY

    errors: dict[str, str] = {}
    out: list[SimpleNamespace] = []
    ids: set[str] = set()
    for raw in rows:
        r = SimpleNamespace(id=str(raw.get("id") or new_id()))
        if r.id in ids:
            raise RefValidationError("Two equipment items have the same id.", {f"{r.id}.tag": "Duplicate item"})
        ids.add(r.id)

        def problem(field: str, message: str) -> None:
            errors[f"{r.id}.{field}"] = message

        for field in _EEL_TEXT:
            setattr(r, field, str(raw.get(field) or "").strip())
        if not r.description:
            problem("description", "Description is required")
        for field, (label, required) in EEL_REFS.items():
            value = raw.get(field) or None
            setattr(r, field, value)
            if value is None:
                if required:
                    problem(field, f"{label} is required")
            elif field == "supplied_from" and value == f"{EEL_SOURCE}/{r.id}":
                problem(field, "An item can't be supplied from itself")
            elif value not in known.get(field, set()) and not (field == "supplied_from" and value == PRIMARY_SUPPLY):
                problem(field, f"That {label.lower()} no longer exists" if field != "supplied_from"
                        else "Not an active distribution panel")
        r.rating_unit = raw.get("rating_unit") or None
        if r.rating_unit is not None and r.rating_unit not in RATING_UNITS:
            problem("rating_unit", "Choose kW or Amps")
        r.phases = raw.get("phases") or None
        if r.phases is not None and r.phases not in PHASES:
            problem("phases", "Choose the phases")
        try:
            r.voltage = coerce(raw.get("voltage"), _INTEGER, None)
            if r.voltage is not None and r.voltage < 0:
                problem("voltage", "Can't be negative")
        except ValueError as exc:
            r.voltage = None
            problem("voltage", str(exc))
        try:
            r.rating = coerce(raw.get("rating"), _DECIMAL, None)
        except ValueError as exc:
            r.rating = None
            problem("rating", str(exc))
        r.is_panel = str(raw.get("is_panel") or "").strip().casefold() in TRUE
        out.append(r)
    _check_unique(out, (("tag", "Tag number", True),), errors)
    if errors:
        raise RefValidationError(f"{len(errors)} problem(s) in the equipment list.", errors)
    return EelList(items=[EelItem(**vars(r)) for r in out])
