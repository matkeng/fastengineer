"""Validation and conversion rules for lists and tables."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from .models import CellValue, ColumnDef, EnumList, RefRow, RefTable, RefValidationError

_WS = re.compile(r"\s+")
TRUE = {"true", "yes", "y", "1", "t", "x", "on"}
FALSE = {"false", "no", "n", "0", "f", "off", ""}


def name_key(name: str) -> str:
    """Names are unique ignoring case and extra spaces."""
    return _WS.sub(" ", name).strip().casefold()


def clean_name(name: str, what: str) -> str:
    n = _WS.sub(" ", name or "").strip()
    if not n:
        raise RefValidationError(f"The {what} needs a name.", {"name": "Required"})
    if len(n) > 120:
        raise RefValidationError(f"The {what} name is too long (120 characters at most).", {"name": "Too long"})
    return n


# -- lists --------------------------------------------------------------------

def check_enum(enum: EnumList) -> EnumList:
    """Codes and values must be filled in and unique within the list (ignoring case)."""
    enum = enum.model_copy(update={"name": clean_name(enum.name, "list")})
    errors: dict[str, str] = {}
    codes: dict[str, str] = {}
    values: dict[str, str] = {}
    items = []
    for item in enum.items:
        item = item.model_copy(update={"code": item.code.strip(), "value": item.value.strip(),
                                       "description": item.description.strip()})
        if not item.code:
            errors[f"{item.id}.code"] = "Code is required"
        elif name_key(item.code) in codes:
            errors[f"{item.id}.code"] = f"Code '{item.code}' is used twice"
        else:
            codes[name_key(item.code)] = item.id
        if not item.value:
            errors[f"{item.id}.value"] = "Value is required"
        elif name_key(item.value) in values:
            errors[f"{item.id}.value"] = f"Value '{item.value}' is used twice"
        else:
            values[name_key(item.value)] = item.id
        items.append(item)
    if errors:
        raise RefValidationError(f"{len(errors)} problem(s) in the list items.", errors)
    return enum.model_copy(update={"items": items})


# -- tables -------------------------------------------------------------------

def check_table_columns(table: RefTable, enums: dict[str, EnumList]) -> RefTable:
    table = table.model_copy(update={"name": clean_name(table.name, "table")})
    errors: dict[str, str] = {}
    seen: set[str] = set()
    cols = []
    for c in table.columns:
        c = c.model_copy(update={"name": _WS.sub(" ", c.name).strip()})
        if not c.name:
            errors[f"{c.id}.name"] = "Column name is required"
        elif name_key(c.name) in seen:
            errors[f"{c.id}.name"] = f"Column '{c.name}' appears twice"
        seen.add(name_key(c.name))
        if c.type == "enum":
            if not c.enum_id:
                errors[f"{c.id}.enum_id"] = "Choose a list"
            elif c.enum_id not in enums:
                errors[f"{c.id}.enum_id"] = "That list no longer exists"
        else:
            c = c.model_copy(update={"enum_id": None})
        cols.append(c)
    if errors:
        raise RefValidationError(f"{len(errors)} problem(s) in the columns.", errors)
    return table.model_copy(update={"columns": cols})


def _norm_decimal(d: Decimal) -> str:
    # Exact and readable: no exponent, no trailing zeros ("2.50" -> "2.5", "1E+2" -> "100").
    s = format(d.normalize(), "f")
    return "0" if s in ("-0", "") else s


def coerce(value: object, col: ColumnDef, enum: EnumList | None) -> CellValue:
    """Convert a submitted value to the column's type. Raises ValueError with a message."""
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return None
    if col.type == "text":
        return str(value)
    if col.type == "integer":
        if isinstance(value, bool):
            raise ValueError("Not a whole number")
        if isinstance(value, int):
            return value
        try:
            d = Decimal(str(value).strip().replace(",", ""))
        except InvalidOperation as exc:
            raise ValueError("Not a whole number") from exc
        if d != d.to_integral_value():
            raise ValueError("Not a whole number")
        return int(d)
    if col.type == "decimal":
        if isinstance(value, bool):
            raise ValueError("Not a number")
        try:
            d = Decimal(str(value).strip().replace(",", ""))
        except InvalidOperation as exc:
            raise ValueError("Not a number") from exc
        if not d.is_finite():
            raise ValueError("Not a number")
        return _norm_decimal(d)
    if col.type == "boolean":
        if isinstance(value, bool):
            return value
        t = str(value).strip().casefold()
        if t in TRUE:
            return True
        if t in FALSE:
            return False
        raise ValueError("Not yes/no")
    # enum: accept an item id, or a code or value (handy when converting or importing)
    if enum is None:
        raise ValueError("The column's list is missing")
    t = str(value).strip()
    for item in enum.items:
        if t == item.id:
            return item.id
    k = name_key(t)
    for item in enum.items:
        if k in (name_key(item.code), name_key(item.value)):
            return item.id
    raise ValueError(f"'{t}' is not in the list {enum.name}")


def validate_row(table: RefTable, values: dict[str, object], enums: dict[str, EnumList],
                 others: list[RefRow]) -> dict[str, CellValue]:
    """Check a row against the table's columns. `others` are the table's other rows (for unique)."""
    errors: dict[str, str] = {}
    out: dict[str, CellValue] = {}
    for col in table.columns:
        try:
            v = coerce(values.get(col.id), col, enums.get(col.enum_id or ""))
        except ValueError as exc:
            errors[col.id] = str(exc)
            continue
        if v is None and col.required:
            errors[col.id] = "Required"
            continue
        if v is not None and col.unique:
            key = name_key(v) if isinstance(v, str) else v
            for r in others:
                o = r.values.get(col.id)
                if o is not None and (name_key(o) if isinstance(o, str) else o) == key:
                    errors[col.id] = "Must be unique; another row already has this value"
                    break
        out[col.id] = v
    if errors:
        raise RefValidationError(f"{len(errors)} value(s) need fixing.", errors)
    return out


def display_value(v: CellValue, col: ColumnDef, enum: EnumList | None) -> str:
    if v is None:
        return ""
    if col.type == "boolean":
        return "Yes" if v else "No"
    if col.type == "enum" and enum:
        item = next((i for i in enum.items if i.id == v), None)
        return item.code if item else str(v)
    return str(v)


def convert_rows(old: RefTable, new: RefTable, rows: list[RefRow],
                 enums: dict[str, EnumList]) -> list[RefRow]:
    """Apply a column change to existing rows: drop removed columns, convert changed
    types (e.g. text '12' -> integer 12, enum code -> another list's item by code).
    Raises RefValidationError with examples if any value can't be converted, or if a
    new required/unique rule doesn't hold for the existing rows."""
    old_cols = {c.id: c for c in old.columns}
    problems: dict[str, list[str]] = {}
    converted: list[RefRow] = []
    for row in rows:
        values: dict[str, CellValue] = {}
        for col in new.columns:
            prev = old_cols.get(col.id)
            v = row.values.get(col.id)
            if prev is not None and v is not None and (prev.type != col.type or prev.enum_id != col.enum_id):
                # Convert through the display text (enum items by code), then to the new type.
                text = display_value(v, prev, enums.get(prev.enum_id or ""))
                try:
                    v = coerce(text, col, enums.get(col.enum_id or ""))
                except ValueError as exc:
                    problems.setdefault(col.id, []).append(f"'{text}': {exc}")
                    continue
            values[col.id] = v
        converted.append(row.model_copy(update={"values": values}))

    for col in new.columns:
        if col.id in problems:
            continue  # conversion errors already explain this column
        if col.required:
            missing = sum(1 for r in converted if r.values.get(col.id) is None)
            if missing:
                problems.setdefault(col.id, []).append(f"{missing} row(s) are empty")
        if col.unique:
            seen: set = set()
            dupes = set()
            for r in converted:
                v = r.values.get(col.id)
                if v is None:
                    continue
                k = name_key(v) if isinstance(v, str) else v
                if k in seen:
                    dupes.add(str(v))
                seen.add(k)
            if dupes:
                problems.setdefault(col.id, []).append(f"duplicate values: {', '.join(sorted(dupes)[:5])}")
    if problems:
        names = {c.id: c.name for c in new.columns}
        fields = {cid: f"Can't apply to existing rows: {'; '.join(msgs[:3])}"
                            + (f" (+{len(msgs) - 3} more)" if len(msgs) > 3 else "")
                  for cid, msgs in problems.items()}
        raise RefValidationError(
            "Existing rows don't fit the new columns: " + ", ".join(names[c] for c in problems) + ".", fields)
    return converted
