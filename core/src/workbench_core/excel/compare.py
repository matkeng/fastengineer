"""Compare two extracted tables (old -> new), matching rows by key value and
columns by header name. Row and column order are ignored.

Row statuses
  added        key only in the new table
  deleted      key only in the old table (row removed)
  struck       row marked deleted in the new table (struck out) but not in the old
  restored     row struck out in the old table but not in the new ("no longer deleted")
  changed      one or more cells in matched columns differ (value or strikethrough)
  unchanged

A row counts as "struck out" when every filled cell is fully struck, or the
key cell itself is fully struck (the usual way a deletion is marked up).
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import Literal

from pydantic import BaseModel

from .models import CellOut, ExtractedRow, ExtractResult

RowStatus = Literal["added", "deleted", "struck", "restored", "changed", "unchanged"]
ColumnStatus = Literal["same", "added", "deleted"]
CellChange = Literal["none", "value", "strike", "both"]

_WS = re.compile(r"\s+")


def _norm(text: str, ignore_case: bool) -> str:
    text = _WS.sub(" ", text).strip()
    return text.casefold() if ignore_case else text


class CompareOptions(BaseModel):
    ignore_case: bool = True  # for keys, header names and cell text
    compare_strike: bool = True  # a change of strikethrough counts as a cell change


class CompareColumn(BaseModel):
    name: str  # name in the new table (old table if deleted)
    old_name: str | None
    a_index: int | None  # column position in the old table
    b_index: int | None  # column position in the new table
    status: ColumnStatus
    is_key: bool
    changed_cells: int = 0


class CompareCell(BaseModel):
    a: CellOut | None  # old value (None: row or column not in the old table)
    b: CellOut | None  # new value
    change: CellChange = "none"


class CompareRow(BaseModel):
    key: str
    status: RowStatus
    a_row: int | None  # Excel row numbers
    b_row: int | None
    changed_cells: int
    duplicate_key: bool
    cells: list[CompareCell]  # aligned with CompareResult.columns


class CompareSummary(BaseModel):
    added: int = 0
    deleted: int = 0
    struck: int = 0
    restored: int = 0
    changed: int = 0
    unchanged: int = 0
    changed_cells: int = 0
    columns_added: int = 0
    columns_deleted: int = 0


class CompareResult(BaseModel):
    a_label: str
    b_label: str
    columns: list[CompareColumn]
    rows: list[CompareRow]
    summary: CompareSummary
    warnings: list[str] = []


def _row_struck(row: ExtractedRow, key_index: int) -> bool:
    return row.strike == "full" or row.cells[key_index].s == "full"


def _same_value(a: CellOut, b: CellOut, ignore_case: bool) -> bool:
    if isinstance(a.v, (int, float)) and isinstance(b.v, (int, float)) \
            and not isinstance(a.v, bool) and not isinstance(b.v, bool):
        return math.isclose(a.v, b.v, rel_tol=1e-9, abs_tol=1e-12)
    return _norm(a.t, ignore_case) == _norm(b.t, ignore_case)


def _strike_sig(c: CellOut) -> tuple:
    """Strike state, including which text is struck for partial strikes."""
    if c.s != "partial" or not c.runs:
        return (c.s,)
    return (c.s, tuple((_WS.sub(" ", r.text).strip(), r.strike) for r in c.runs if r.text.strip()))


def _cell_change(a: CellOut, b: CellOut, opts: CompareOptions) -> CellChange:
    value = not _same_value(a, b, opts.ignore_case)
    strike = opts.compare_strike and _strike_sig(a) != _strike_sig(b)
    if value and strike:
        return "both"
    return "value" if value else "strike" if strike else "none"


def _match_columns(a: ExtractResult, b: ExtractResult, ignore_case: bool) -> list[CompareColumn]:
    a_by_name = {_norm(c.name, ignore_case): c for c in a.columns}
    used_a: set[int] = set()
    columns: list[CompareColumn] = []
    for c in b.columns:
        if c.index == b.key_column:
            # The two key columns always pair up, whatever they are called.
            ac = a.columns[a.key_column]
        else:
            ac = a_by_name.get(_norm(c.name, ignore_case))
            if ac is not None and ac.index == a.key_column:
                ac = None
        if ac is not None and ac.index not in used_a:
            used_a.add(ac.index)
            columns.append(CompareColumn(name=c.name, old_name=ac.name, a_index=ac.index,
                                         b_index=c.index, status="same",
                                         is_key=c.index == b.key_column))
        else:
            columns.append(CompareColumn(name=c.name, old_name=None, a_index=None,
                                         b_index=c.index, status="added", is_key=False))
    for c in a.columns:
        if c.index not in used_a:
            columns.append(CompareColumn(name=c.name, old_name=c.name, a_index=c.index,
                                         b_index=None, status="deleted", is_key=False))
    # Key first, then new-table order, removed columns last.
    columns.sort(key=lambda c: (not c.is_key, c.status == "deleted"))
    return columns


def _group(rows: list[ExtractedRow], ignore_case: bool) -> dict[str, list[ExtractedRow]]:
    groups: dict[str, list[ExtractedRow]] = defaultdict(list)
    for r in rows:
        groups[_norm(r.key, ignore_case)].append(r)
    return groups


def compare_tables(a: ExtractResult, b: ExtractResult, options: CompareOptions | None = None,
                   a_label: str = "Old", b_label: str = "New") -> CompareResult:
    opts = options or CompareOptions()
    columns = _match_columns(a, b, opts.ignore_case)
    a_groups, b_groups = _group(a.rows, opts.ignore_case), _group(b.rows, opts.ignore_case)

    warnings: list[str] = []
    dupes = sorted({g[0].key for g in a_groups.values() if len(g) > 1}
                   | {g[0].key for g in b_groups.values() if len(g) > 1})
    if dupes:
        warnings.append(
            f"{len(dupes)} key value(s) are duplicated; duplicates are paired in the order they appear: "
            + ", ".join(dupes[:8]) + ("…" if len(dupes) > 8 else "")
        )
    if a.columns[a.key_column].name != b.columns[b.key_column].name:
        warnings.append(f"Key columns have different names: '{a.columns[a.key_column].name}' "
                        f"(old) and '{b.columns[b.key_column].name}' (new); matched anyway.")

    summary = CompareSummary(
        columns_added=sum(c.status == "added" for c in columns),
        columns_deleted=sum(c.status == "deleted" for c in columns),
    )
    out: list[CompareRow] = []
    keys = list(dict.fromkeys([*b_groups, *a_groups]))  # new-table order, then removed keys
    for key in keys:
        a_rows, b_rows = a_groups.get(key, []), b_groups.get(key, [])
        dup = len(a_rows) > 1 or len(b_rows) > 1
        for i in range(max(len(a_rows), len(b_rows))):
            ar = a_rows[i] if i < len(a_rows) else None
            br = b_rows[i] if i < len(b_rows) else None
            was = ar is not None and _row_struck(ar, a.key_column)
            now = br is not None and _row_struck(br, b.key_column)
            # When the whole row was struck out or restored, its cells' strike changes
            # are implied by the row status; only report real value changes.
            row_strike_changed = ar is not None and br is not None and was != now
            cells: list[CompareCell] = []
            changed = 0
            for col in columns:
                ac = ar.cells[col.a_index] if ar is not None and col.a_index is not None else None
                bc = br.cells[col.b_index] if br is not None and col.b_index is not None else None
                change: CellChange = "none"
                if ac is not None and bc is not None:
                    change = _cell_change(ac, bc, opts)
                    if row_strike_changed:
                        change = "value" if change in ("value", "both") else "none"
                    if change != "none":
                        changed += 1
                        col.changed_cells += 1
                cells.append(CompareCell(a=ac, b=bc, change=change))

            if ar is None:
                status: RowStatus = "added"
            elif br is None:
                status = "deleted"
            else:
                if now and not was:
                    status = "struck"
                elif was and not now:
                    status = "restored"
                else:
                    status = "changed" if changed else "unchanged"
            setattr(summary, status, getattr(summary, status) + 1)
            summary.changed_cells += changed
            out.append(CompareRow(
                key=(br or ar).key, status=status,
                a_row=ar.row if ar else None, b_row=br.row if br else None,
                changed_cells=changed, duplicate_key=dup, cells=cells,
            ))

    return CompareResult(a_label=a_label, b_label=b_label, columns=columns, rows=out,
                         summary=summary, warnings=warnings)
