# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""The columns of the Project Master lists, which a project can edit.

Each of the four master lists (Cable Schedule, Equipment List, Instrument List, IO List)
starts with the built-in columns of its list (loadgen.LISTS) and a project can rename, add,
reorder and delete them. Generator and Confirmed always follow and are not edited here.

Cells are kept by column name (in load type and equipment type rows, and in deliverables'
column choices and filters), so a rename rewrites them and a delete drops them: see
`plan_change` and `rewrite_rows`. Issued revisions keep the header they were issued with.

Some columns can be moved but not renamed or deleted (`PROTECTED`): the column revisions are
compared by, and the cable columns that "Per power cable" rows fill in.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..refdata.models import RefValidationError
from ..refdata.validate import name_key
from .loadgen import LISTS, REPEAT, TEMPLATE_LISTS
from .master import EXTRA_COLUMNS

#: Columns that can be moved but not renamed or deleted: list key -> names.
PROTECTED: dict[str, tuple[str, ...]] = {
    k: (LISTS[k].diff_key, *(("Cable Type", "Cores", "Cable Code") if k == "cable_schedule" else ())) for k in TEMPLATE_LISTS}
#: Names a list's own column can't have.
RESERVED: tuple[str, ...] = (*EXTRA_COLUMNS, REPEAT)
MAX_COLUMNS = 60
MAX_NAME = 60


class MasterColumns(BaseModel):
    """The project's columns of each master list, in order (list key -> names)."""
    lists: dict[str, list[str]] = Field(default_factory=dict)

    def of(self, key: str) -> list[str]:
        return list(self.lists.get(key) or LISTS[key].columns)

    def all(self) -> dict[str, list[str]]:
        return {k: self.of(k) for k in TEMPLATE_LISTS}


def default_master_columns() -> MasterColumns:
    return MasterColumns(lists={k: list(LISTS[k].columns) for k in TEMPLATE_LISTS})


class ColumnEdit(BaseModel):
    """One column as edited: its name now, and the name it had (`was`; "" for a new column)."""
    name: str
    was: str = ""


class ColumnChange(BaseModel):
    """What saving edited columns does to one list."""
    columns: list[str]
    renames: dict[str, str] = Field(default_factory=dict)  # old name -> new name
    deletes: list[str] = Field(default_factory=list)
    added: list[str] = Field(default_factory=list)


def plan_change(old: MasterColumns, edits: dict[str, list[ColumnEdit]]) -> dict[str, ColumnChange]:
    """Check the edited columns of each list against the current ones and work out the
    renames, deletes and new columns. Lists not in `edits` are unchanged. Raises
    RefValidationError (field `<list key>.<position>` or `<list key>`) on a problem."""
    errors: dict[str, str] = {}
    out: dict[str, ColumnChange] = {}
    for key, cols in edits.items():
        if key not in TEMPLATE_LISTS:
            errors[key] = f"'{key}' is not a master list"
            continue
        before = old.of(key)
        by_key = {name_key(c): c for c in before}
        reserved = {name_key(r) for r in RESERVED}
        seen: dict[str, int] = {}
        used: set[str] = set()
        change = ColumnChange(columns=[])
        if len(cols) > MAX_COLUMNS:
            errors[key] = f"A list can have at most {MAX_COLUMNS} columns"
        for i, c in enumerate(cols):
            name = " ".join(c.name.split())
            was = by_key.get(name_key(c.was)) if c.was.strip() else None
            field = f"{key}.{i}"
            if c.was.strip() and was is None:
                errors[field] = f"'{c.was}' is not a column of the list"
                continue
            if was is not None:
                if was in used:
                    errors[field] = f"'{was}' is edited twice"
                used.add(was)
            if not name:
                errors[field] = "A column needs a name"
                continue
            if len(name) > MAX_NAME:
                errors[field] = f"At most {MAX_NAME} characters"
            if name_key(name) in reserved:
                errors[field] = f"'{name}' is kept for the master list's own use"
            if name_key(name) in seen:
                errors[field] = f"'{name}' is in the list twice"
            seen[name_key(name)] = i
            if was is None:
                change.added.append(name)
            elif was != name:
                change.renames[was] = name
            change.columns.append(name)
        change.deletes = [c for c in before if c not in used]
        for p in PROTECTED[key]:
            if p in change.deletes or p in change.renames:
                errors[key] = f"'{p}' can be moved but not renamed or deleted"
        # a new column can't take the name of one that is renamed or deleted in the same save
        gone = {name_key(c) for c in [*change.deletes, *change.renames]}
        for name in change.added:
            if name_key(name) in gone:
                errors[f"{key}.{seen[name_key(name)]}"] = f"'{name}' was a column: rename it instead of adding it again"
        out[key] = change
    if errors:
        raise RefValidationError(f"{len(errors)} problem(s) in the master list columns.", errors)
    return out


def rewrite_rows(rows: dict[str, list[dict[str, str]]], changes: dict[str, ColumnChange]) -> tuple[dict[str, list[dict[str, str]]], int]:
    """Template rows (list key -> rows of cells by column name) with renamed columns' cells
    moved to the new name and deleted columns' cells dropped. Returns the rows and how many
    non-blank cells were dropped. Rows left with no cell are dropped too."""
    out: dict[str, list[dict[str, str]]] = {}
    dropped = 0
    for key, list_rows in rows.items():
        ch = changes.get(key)
        if ch is None:
            out[key] = list_rows
            continue
        deletes = set(ch.deletes)
        kept = []
        for row in list_rows:
            new = {}
            for c, v in row.items():
                if c in deletes:
                    dropped += bool(str(v).strip())
                    continue
                new[ch.renames.get(c, c)] = v
            if any(c != REPEAT for c in new):
                kept.append(new)
        if kept:
            out[key] = kept
    return out, dropped


def rename_in(names: list[str], ch: ColumnChange) -> list[str]:
    """Column names (a deliverable's choice) with renames applied and deleted ones left out,
    matched ignoring case and extra spaces."""
    renames = {name_key(a): b for a, b in ch.renames.items()}
    deletes = {name_key(d) for d in ch.deletes}
    return [renames.get(name_key(n), n) for n in names if name_key(n) not in deletes]


__all__ = ["PROTECTED", "RESERVED", "MasterColumns", "ColumnEdit", "ColumnChange", "default_master_columns",
           "plan_change", "rewrite_rows", "rename_in", "RefValidationError"]
