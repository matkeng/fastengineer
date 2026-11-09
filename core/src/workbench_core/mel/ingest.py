# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Read a source table and make headers and key values unique (PRD 5.1)."""

from __future__ import annotations

import csv
import io

from ..excel.models import ExtractResult


class IngestError(ValueError):
    pass


def unique_headers(headers: list[str]) -> list[str]:
    """Strip; blank -> 'Blank'; repeats 'X' -> 'X_1', 'X_2' ... (deterministic)."""
    out: list[str] = []
    seen: dict[str, int] = {}
    used: set[str] = set()
    for h in headers:
        base = (h or "").strip() or "Blank"
        name = base
        while name in used:
            seen[base] = seen.get(base, 0) + 1
            name = f"{base}_{seen[base]}"
        used.add(name)
        out.append(name)
    return out


def unique_keys(rows: list[dict[str, str]], key: str) -> int:
    """Strip key values; blank -> 'Blank'; duplicates -> 'K_1', 'K_2' ... in place.
    Returns how many keys were changed."""
    changed = 0
    used: set[str] = set()
    counters: dict[str, int] = {}
    for row in rows:
        base = (row.get(key) or "").strip() or "Blank"
        value = base
        while value in used:
            counters[base] = counters.get(base, 0) + 1
            value = f"{base}_{counters[base]}"
        used.add(value)
        if value != row.get(key):
            changed += 1
        row[key] = value
    return changed


def _decode(data: bytes) -> tuple[str, list[str]]:
    for enc in ("utf-8-sig",):
        try:
            return data.decode(enc), []
        except UnicodeDecodeError:
            pass
    # Excel's "CSV" on Windows is usually cp1252; accept it rather than refuse the file.
    return data.decode("cp1252", errors="replace"), [
        "The file is not UTF-8; it was read as Windows-1252. Check accented characters."]


def parse_csv(data: bytes) -> tuple[list[str], list[str], list[dict[str, str]], list[str]]:
    """Returns (headers_original, headers, rows, warnings)."""
    if not data.strip():
        raise IngestError("The file is empty.")
    text, warnings = _decode(data)
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    try:
        original = next(reader)
    except StopIteration as exc:
        raise IngestError("The file has no header row.") from exc
    headers = unique_headers(original)
    rows: list[dict[str, str]] = []
    for line in reader:
        if not any(cell.strip() for cell in line):
            continue  # skip blank lines
        line = line + [""] * (len(headers) - len(line))
        if len(line) > len(headers):
            warnings.append(f"Row {reader.line_num} has more cells than headers; extras ignored.")
        rows.append({h: line[i].strip() for i, h in enumerate(headers)})
    if not rows:
        raise IngestError("The file has a header row but no data.")
    return original, headers, rows, warnings


def rows_from_extract(ex: ExtractResult) -> tuple[list[str], list[str], list[dict[str, str]]]:
    """Use an Excel table from the import wizard as the source (display text of each cell)."""
    original = [c.name for c in ex.columns]
    headers = unique_headers(original)
    rows = [{h: r.cells[i].t for i, h in enumerate(headers)} for r in ex.rows]
    return original, headers, rows
