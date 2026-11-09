# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Change report between two builds (PRD 9): matched on the DiffKey column, duplicate
keys disambiguated by occurrence (key, key#2, ...), columns compared by header name."""

from __future__ import annotations

from .models import ChangedCell, ChangeEntry, ChangeReport, OutputRow, Scalar
from .text import to_text


def _same(a: Scalar, b: Scalar) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool):
        return float(a) == float(b)
    return type(a) is type(b) and a == b if a is not None and b is not None else to_text(a) == to_text(b) == ""


def _keyed(header: list[str], rows: list[OutputRow], key_col: str) -> dict[str, dict[str, Scalar]]:
    try:
        ki = [h.lower() for h in header].index(key_col.lower())
    except ValueError:
        ki = None
    out: dict[str, dict[str, Scalar]] = {}
    seen: dict[str, int] = {}
    for i, r in enumerate(rows):
        if r.run_row_id is None and all(v is None or v == "" for v in r.cells):
            continue  # separator
        base = to_text(r.cells[ki]) if ki is not None and ki < len(r.cells) else f"row {i + 1}"
        n = seen[base] = seen.get(base, 0) + 1
        key = base if n == 1 else f"{base}#{n}"
        out[key] = {h: (r.cells[j] if j < len(r.cells) else None) for j, h in enumerate(header)}
    return out


def change_report(old_header: list[str], old_rows: list[OutputRow], new_header: list[str],
                  new_rows: list[OutputRow], key_col: str) -> ChangeReport:
    old = _keyed(old_header, old_rows, key_col)
    new = _keyed(new_header, new_rows, key_col)
    rep = ChangeReport()
    cols = list(dict.fromkeys([*new_header, *old_header]))
    for k, row in new.items():
        if k not in old:
            rep.added += 1
            rep.entries.append(ChangeEntry(key=k, kind="added"))
            continue
        prev = old[k]
        cells = [ChangedCell(column=c, old=prev.get(c), new=row.get(c)) for c in cols
                 if not _same(prev.get(c), row.get(c))]
        if cells:
            rep.changed += 1
            rep.entries.append(ChangeEntry(key=k, kind="changed", cells=cells))
    for k in old:
        if k not in new:
            rep.removed += 1
            rep.entries.append(ChangeEntry(key=k, kind="removed"))
    return rep
