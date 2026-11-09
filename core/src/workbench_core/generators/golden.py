# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Golden tests (PRD 17.1): import each generator workbook, build with its stored config, and
compare with the expected counts and, when the workbook holds one, the stored Output."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from .expand import build
from .models import BuildResult, OutputRow
from .text import to_text
from .xlsx_import import import_workbook

# Expected figures live next to the workbooks, outside the repository, in expected.json:
#   {"<generator id>": {"runs": ..., "rows": ..., "output_rows": ..., "cells": ...,
#                       "unresolved": ..., "no_template": ..., "duplicate_ids": [...]}, ...}
# Any subset of keys may be given. "runs" counts runs selected for the build (key present, in
# the run range), with or without a template.
EXPECTED_FILE = "expected.json"


def load_expected(folder: str | Path) -> dict[str, dict]:
    p = Path(folder) / EXPECTED_FILE
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


class GoldenCase(BaseModel):
    workbook: str
    generator: str
    passed: bool
    actual: dict
    expected: dict
    failures: list[str] = Field(default_factory=list)
    output_compared: bool = False
    rebuild_changes: int = 0
    build_ms: float = 0


def measure(r: BuildResult, dup_ids: list[str]) -> dict:
    s = r.stats
    return {"runs": s.processed + s.no_template, "rows": s.rows_written, "output_rows": s.output_rows,
            "cells": s.non_empty_cells, "unresolved": r.unresolved_count, "no_template": s.no_template,
            "duplicate_ids": dup_ids}


def _cmp(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool):
        return float(a) == float(b)
    if a in (None, "") and b in (None, ""):
        return True
    return type(a) is type(b) and a == b


def compare_output(r: BuildResult, header: list[str], rows: list[list]) -> list[str]:
    """Cell by cell by header name, including type (first 20 differences)."""
    diffs: list[str] = []
    idx = {h.lower(): i for i, h in enumerate(header) if h}
    while rows and all(v in (None, "") for v in rows[-1]):
        rows = rows[:-1]
    if len(rows) != len(r.rows):
        diffs.append(f"row count {len(r.rows)} != stored {len(rows)}")
    for n, (mine, theirs) in enumerate(zip(r.rows, rows), start=2):
        for j, h in enumerate(r.header):
            k = idx.get(h.lower())
            if k is None:
                continue
            a, b = mine.cells[j], theirs[k] if k < len(theirs) else None
            if not _cmp(a, b):
                diffs.append(f"row {n} '{h}': {a!r} != stored {b!r}")
                if len(diffs) >= 20:
                    return diffs
    return diffs


def run_golden(folder: str | Path) -> list[GoldenCase]:
    out: list[GoldenCase] = []
    expected = load_expected(folder)
    for p in sorted(Path(folder).glob("*.xls[xm]")):
        imp = import_workbook(p)
        g = imp.generator
        r = build(g)
        exp = expected.get(g.id, {})
        act = measure(r, imp.report.duplicate_template_ids)
        fails = [f"{k}: {act.get(k)!r} != expected {v!r}" for k, v in exp.items() if act.get(k) != v]
        case = GoldenCase(workbook=p.name, generator=g.id, passed=False, actual=act, expected=exp, build_ms=r.stats.duration_ms)
        if imp.baseline_rows:
            case.output_compared = True
            fails += compare_output(r, imp.baseline_header or [], imp.baseline_rows)
        again = build(g, previous=r)
        ch = again.changes
        case.rebuild_changes = (ch.added + ch.removed + ch.changed) if ch else 0
        if case.rebuild_changes:
            fails.append(f"rebuild with unchanged inputs reports {case.rebuild_changes} changes")
        case.failures, case.passed = fails, not fails
        out.append(case)
    return out


def rows_as_output(rows: list[list]) -> list[OutputRow]:
    return [OutputRow(cells=r, run_row_id=None if all(v in (None, "") for v in r) else "baseline") for r in rows]


__all__ = ["EXPECTED_FILE", "load_expected", "GoldenCase", "compare_output", "measure", "run_golden", "rows_as_output", "to_text"]
