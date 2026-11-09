# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Live preview for the template editor: expand one run, with each cell's template source."""

from __future__ import annotations

from pydantic import BaseModel, Field

from .expand import build
from .models import BuildError, Generator, Scalar
from .text import to_text


class PreviewRow(BaseModel):
    cells: list[Scalar]
    sources: list[str]  # template text of each cell ("" for blank, "computed: kind" for computed)
    template_id: str | None = None
    template_seq: int | None = None


class PreviewResult(BaseModel):
    header: list[str]
    rows: list[PreviewRow] = Field(default_factory=list)
    message: str = ""


def _source(cell, column) -> str:
    if cell is None:
        return ""
    if cell.kind == "computed":
        comp = cell.override or column.computed
        return f"computed: {comp.kind}" if comp else "computed"
    return cell.text if cell.text is not None else to_text(cell.value)


def preview(gen: Generator, run_row_id: str, template_id: str | None = None) -> PreviewResult:
    """Build the single runsheet row `run_row_id`, ignoring the run range and locked flag.
    With `template_id`, the row is expanded through that template whatever its key says."""
    row = next((r for r in gen.runsheet.rows if r.id == run_row_id), None)
    if row is None:
        return PreviewResult(header=[], message=f"runsheet row {run_row_id} not found")
    one = gen.model_copy(deep=False)
    one.runsheet = gen.runsheet.model_copy(update={"rows": [row]})
    # no previous build is passed, so a locked run is regenerated (the preview shows what it would be)
    one.config = gen.config.model_copy(update={"run_from": None, "run_up_to": None, "stop_at_blank_key": False})
    if template_id is not None:
        from .expand import discover_tags, find_tag
        tags = discover_tags(one)
        kp = find_tag(tags, one.config.key_placeholder)
        kp = tags[0][0] if kp is None else kp
        values = list(row.values) + [None] * max(0, kp + 1 - len(row.values))
        tpl = next((t for t in gen.templates if t.id == template_id), None)
        values[kp] = tpl.id_value if tpl is not None else template_id
        one.runsheet = one.runsheet.model_copy(update={"rows": [row.model_copy(update={"values": values})]})
    try:
        res = build(one, use_config_range=False)
    except BuildError as exc:
        return PreviewResult(header=[], message=str(exc))
    tmap = {}
    for t in gen.templates:
        tmap.setdefault(t.id, t)
    out = PreviewResult(header=res.header)
    for r in res.rows:
        if r.run_row_id is None:
            continue
        t = tmap.get(r.template_id or "")
        cells = t.rows[r.template_seq - 1].cells if t and r.template_seq else []
        n = len(gen.output_columns)
        out.rows.append(PreviewRow(cells=r.cells, template_id=r.template_id, template_seq=r.template_seq,
                                   sources=[to_text(t.id_value) if t else ""] + [_source(cells[i] if i < len(cells) else None, gen.output_columns[i]) for i in range(n)]))
    if not out.rows:
        w = next((w.detail or w.item for w in res.warnings if w.code == "missingTemplate"), "")
        out.message = f"no rows: {w}" if w else "no rows (blank, nr or none key)"
    return out
