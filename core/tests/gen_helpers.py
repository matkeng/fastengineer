# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Small builders for synthetic generator fixtures."""

from __future__ import annotations

from workbench_core.generators.models import (ColumnDef, Generator, GeneratorConfig, OutputColumn, RunRow, Runsheet,
                                              Template, TemplateCell, TemplateRow)


def cell(v) -> TemplateCell:
    if isinstance(v, TemplateCell):
        return v
    if isinstance(v, str) and v.startswith("="):
        return TemplateCell(kind="formula", text=v)
    if isinstance(v, str) and "F=" in v:
        return TemplateCell(kind="late", text=v)
    if isinstance(v, str) and "<<" in v:
        return TemplateCell(kind="text", text=v)
    return TemplateCell(kind="literal", value=v)


def make_gen(tags: list[str], runs: list[list], columns: list[str], templates: dict, *, parents=None,
             computed: dict | None = None, gen_id: str = "test", **cfg) -> Generator:
    """templates: {id: [[cell per column], ...]}; computed: {column: Computed}."""
    out_cols = [OutputColumn(name=c, computed=(computed or {}).get(c)) for c in columns]
    tpls = []
    for tid, rows in templates.items():
        trs = []
        for r in rows:
            cells = []
            for j, v in enumerate(r):
                if v == "@computed":
                    cells.append(TemplateCell(kind="computed"))
                else:
                    cells.append(cell(v))
            trs.append(TemplateRow(cells=cells))
        tpls.append(Template(id=str(tid), id_value=tid, rows=trs))
    return Generator(
        id=gen_id, config=GeneratorConfig(**cfg),
        runsheet=Runsheet(columns=[ColumnDef(name=t.strip("<>"), tag=t) for t in tags],
                          rows=[RunRow(id=str(i + 3), values=r) for i, r in enumerate(runs)]),
        output_columns=out_cols, templates=tpls, parents=parents)


def col(result, name: str) -> list:
    i = result.header.index(name)
    return [r.cells[i] for r in result.rows if r.run_row_id is not None]
