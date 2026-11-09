# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""The expansion engine (PRD section 5): runsheet x templates -> output rows.

Compatibility mode reproduces the Excel/VBA generator engine; standard mode applies the Appendix D fixes
that are already agreed (case-insensitive parents, exact Code Check, full space collapse,
leading-only F=, row directives, trimmed parent text)."""

from __future__ import annotations

import re
import time
from collections.abc import Callable

from .computed import NA, TableIndex, evaluate_computed, is_error
from .diff import change_report
from .expr import ExprError, evaluate
from .models import (BuildError, BuildResult, BuildStats, Finding, Generator, OutputRow, Scalar,
                     Template, TemplateCell)
from .text import (NO_VALUE, PARENT_NOT_FOUND, as_typed, collapse_spaces, contains_ci, is_truthy,
                   replace_ci, to_text)

ENGINE_VERSION = "workbench-generators 1.0.0"
TOKEN = re.compile(r"<<[^<>]*>>")
DELETE_ROW, MANUAL_ROW = "<<DELETE ROW>>", "<<MANUAL ROW>>"


def is_tag(text: object) -> bool:
    s = str(text or "").strip()
    return s.startswith("<<") and s.endswith(">>") and len(s) > 4


def discover_tags(gen: Generator) -> list[tuple[int, str]]:
    """PRD 5.2: (column position, tag) in column order. Duplicates are fatal."""
    tags: list[tuple[int, str]] = []
    seen: dict[str, str] = {}
    for i, col in enumerate(gen.runsheet.columns):
        if not is_tag(col.tag):
            continue
        t = col.tag.strip()
        if t.lower() in seen:
            raise BuildError("tags", f"duplicate tag {t} in column {i + 1} ('{col.name}'); first seen as {seen[t.lower()]}")
        seen[t.lower()] = t
        tags.append((i, t))
    if not tags:
        raise BuildError("tags", "the runsheet tag row has no <<tags>>")
    return tags


def find_tag(tags: list[tuple[int, str]], name: str) -> int | None:
    for pos, t in tags:
        if t.lower() == name.strip().lower():
            return pos
    return None


def template_index(gen: Generator, standard: bool = False) -> tuple[dict[str, Template], list[str]]:
    """First block wins for a repeated ID (PRD 4.2). Returns (index, duplicate IDs)."""
    idx: dict[str, Template] = {}
    dups: list[str] = []
    for t in gen.templates:
        k = t.id.lower() if standard else t.id
        if k in idx:
            dups.append(t.id)
            continue
        idx[k] = t
        if t.duplicate_blocks:
            dups.append(t.id)
    return idx, list(dict.fromkeys(dups))


class Parents:
    def __init__(self, records: list[tuple[str, str]] | None, include_tag: bool, standard: bool):
        self.present = records is not None
        self.include_tag, self.standard = include_tag, standard
        self.map: dict[str, str] = {}
        self.duplicates: list[str] = []
        for tag, desc in records or []:
            k = to_text(tag)
            k = k.lower() if standard else k
            if k == "":
                continue
            if k in self.map:
                self.duplicates.append(to_text(tag))
                continue
            self.map[k] = to_text(desc)

    def lookup(self, tag: str) -> tuple[bool, str]:
        d = self.map.get(tag.lower() if self.standard else tag)
        if d is None:
            return False, PARENT_NOT_FOUND
        if self.include_tag:
            d = f"{d} ({tag}) "
            if self.standard:
                d = d.strip()  # Appendix D item 13
        return True, d


def _derive(transform: str, src: str, default: str, values: dict[str, str], gen: Generator,
            parents: Parents, seq: int) -> str:
    t = (transform or "").strip()
    tl = t.lower()
    if tl in ("", "none", "copy"):
        out = src
    elif tl in ("strip-hyphens", "s"):
        out = src.replace("-", "")
    elif tl in ("parent", "p"):
        out = parents.lookup(src)[1] if parents.present else ""
    elif tl == "upper":
        out = src.upper()
    elif tl == "lower":
        out = src.lower()
    elif tl == "trim":
        out = src.strip()
    elif tl.startswith("left:"):
        out = src[: int(t.split(":", 1)[1] or 0)]
    elif tl.startswith("right:"):
        n = int(t.split(":", 1)[1] or 0)
        out = src[-n:] if n else ""
    elif tl.startswith("concat:"):
        out = src + values.get(t.split(":", 1)[1].strip().lower(), "")
    elif tl.startswith("route:"):
        other = values.get(t.split(":", 1)[1].strip().lower(), "")
        out = ""
        for r in gen.routes:
            if {r.a.lower(), r.b.lower()} == {src.lower(), other.lower()} or (r.a.lower() == src.lower() and r.b.lower() == other.lower()):
                out = to_text(r.length)
                break
    elif tl == "prefix":
        out = next((p.prefix for p in gen.cable_prefixes if p.cable_type.lower() == src.lower()), "")
    elif tl == "seq":
        return str(seq)
    elif tl == "fixed":
        out = default
    else:
        raise BuildError("derived tags", f"unknown transform '{transform}'")
    return out if out != "" else (default or "")


class _Run:
    """Everything needed to expand text for one run."""

    def __init__(self, gen: Generator, tags: list[tuple[int, str]], row_values: list[Scalar], parents: Parents,
                 mech_pos: int | None, suf_pos: int | None):
        cfg = gen.config
        self.gen, self.parents, self.cfg = gen, parents, cfg
        self.standard = cfg.mode == "standard"
        fmt = cfg.date_format
        self.subs: list[tuple[str, str, str, str]] = []  # (base_lower, tag, value, stripped)
        self.values: dict[str, str] = {}
        for pos, tag in tags:
            v = to_text(row_values[pos] if pos < len(row_values) else None, fmt)
            self.values[tag.lower()] = v
            self.subs.append((tag[:-2].lower(), tag, v, v.replace("-", "")))
        self.parent_text: str | None = None
        if parents.present and mech_pos is not None and suf_pos is not None:
            mech = to_text(row_values[mech_pos] if mech_pos < len(row_values) else None, fmt)
            suf = to_text(row_values[suf_pos] if suf_pos < len(row_values) else None, fmt)
            found, p = parents.lookup(mech)
            self.parent_text = (p + suf if found else suf) or NO_VALUE

    def derived(self, seq: int) -> list[tuple[str, str]]:
        out = []
        for d in self.gen.derived_tags:
            name = d.name.strip()
            if not name.startswith("<<"):
                name = f"<<{name}>>"
            src = d.source.strip()
            src_v = self.values.get(src.lower(), src if not is_tag(src) else "")
            out.append((name, _derive(d.transform, src_v, d.default, self.values, self.gen, self.parents, seq)))
        return out

    def expand(self, s: str, derived: list[tuple[str, str]]) -> str:
        if "<<" in s:
            low = s.lower()
            for base, tag, v, stripped in self.subs:
                if base in low:
                    s = replace_ci(s, tag, v or NO_VALUE)
                    s = replace_ci(s, tag[:-2] + "_S>>", stripped or NO_VALUE)
                    if self.parents.present:
                        s = replace_ci(s, tag[:-2] + "_P>>", self.parents.lookup(v)[1])
                    low = s.lower()
            for name, v in derived:
                s = replace_ci(s, name, v or NO_VALUE)
            if self.parent_text is not None:
                s = replace_ci(s, "<<PARENT>>", self.parent_text)
        if self.cfg.collapse_spaces and "  " in s:
            s = collapse_spaces(s, full=self.standard)
        if self.cfg.replace_f_equals and "F=" in s:
            s = ("=" + s[2:] if s.startswith("F=") else s) if self.standard else s.replace("F=", "=")
        return s


def _needs_expand(s: str, cfg) -> bool:
    return "<<" in s or (cfg.collapse_spaces and "  " in s) or (cfg.replace_f_equals and "F=" in s)


def _write(s: str, standard: bool) -> tuple[Scalar, bool]:
    """'As typed' (PRD 5.7). Returns (value, is_formula)."""
    if s.startswith("=") and len(s) > 1:
        try:
            return evaluate(s), True
        except ExprError:
            return s, False  # unparseable formula: stored as text
    return as_typed(s), False


def _run_number(v: Scalar) -> float:
    s = to_text(v).strip()
    try:
        return float(s)
    except ValueError:
        return 0.0  # non-numeric run counts as 0 (Appendix D item 3)


def build(gen: Generator, previous: BuildResult | None = None, run_from: float | None = None,
          run_up_to: float | None = None, use_config_range: bool = True,
          progress: Callable[[int, int], None] | None = None) -> BuildResult:
    t0 = time.perf_counter()
    phase: dict[str, float] = {}
    cfg = gen.config
    standard = cfg.mode == "standard"
    if use_config_range:
        run_from = cfg.run_from if run_from is None else run_from
        run_up_to = cfg.run_up_to if run_up_to is None else run_up_to

    tags = discover_tags(gen)
    key_pos = find_tag(tags, cfg.key_placeholder)
    if key_pos is None:
        key_pos = tags[0][0]
    run_pos = find_tag(tags, cfg.run_placeholder)
    locked_pos = find_tag(tags, cfg.locked_placeholder)
    if (run_from is not None or run_up_to is not None) and run_pos is None:
        raise BuildError("run selection", f"a run range is set but the runsheet has no {cfg.run_placeholder} column")
    if not gen.runsheet.rows:
        raise BuildError("runsheet", "the runsheet has no data rows")
    parents = Parents(gen.parents if cfg.use_parents else None, cfg.parent_include_tag, standard)
    mech_pos, suf_pos = find_tag(tags, "<<MECH>>"), find_tag(tags, "<<SUF>>")
    tindex, dup_ids = template_index(gen, standard)
    tables = {name: TableIndex(t) for name, t in gen.tables.items()}
    names = [c.name for c in gen.output_columns]
    lower_names = {n.lower(): i for i, n in reversed(list(enumerate(names)))}
    header = [gen.id_column, *names]
    run_col = lower_names.get(cfg.run_column.lower())
    prev_by_run: dict[str, list[list[Scalar]]] = {}
    if previous is not None:
        try:
            prc = [h.lower() for h in previous.header].index(cfg.run_column.lower())
        except ValueError:
            prc = None
        if prc is not None:
            for r in previous.rows:
                if r.run_row_id is None and all(v in (None, "") for v in r.cells):
                    continue
                k = to_text(r.cells[prc]) if prc < len(r.cells) else ""
                prev_by_run.setdefault(k, []).append(r)
    phase["prepare"] = (time.perf_counter() - t0) * 1000

    warnings: list[Finding] = []
    stats = BuildStats()
    out: list[OutputRow] = []
    missing: list[tuple[str, str]] = []
    t1 = time.perf_counter()
    total = len(gen.runsheet.rows)
    for n, rr in enumerate(gen.runsheet.rows):
        if progress and n % 200 == 0:
            progress(n, total)
        vals = rr.values
        key = to_text(vals[key_pos] if key_pos < len(vals) else None, cfg.date_format)
        if key.strip() == "":
            if cfg.stop_at_blank_key:
                break
            stats.blank_key += 1
            continue
        if key.strip().lower() in ("nr", "none"):
            stats.skipped += 1
            continue
        run_text = to_text(vals[run_pos], cfg.date_format) if run_pos is not None and run_pos < len(vals) else ""
        if run_from is not None or run_up_to is not None:
            run = _run_number(vals[run_pos] if run_pos < len(vals) else None)
            if (run_from is not None and run < run_from) or (run_up_to is not None and run >= run_up_to):
                stats.filtered += 1
                continue

        block: list[OutputRow] | None = None
        if locked_pos is not None and locked_pos < len(vals) and is_truthy(vals[locked_pos]):
            prev_rows = prev_by_run.get(run_text)
            if prev_rows:
                block = [OutputRow(cells=list(r.cells), run_row_id=rr.id, template_id=r.template_id,
                                   template_seq=r.template_seq, locked=True) for r in prev_rows]
                stats.locked_used += 1
            else:
                warnings.append(Finding(severity="WARN", code="lockedNotFound", item=f"run {run_text}",
                                        detail="locked, but the previous build has no rows for this run; regenerated",
                                        where=f"runsheet row {rr.id}"))
        if block is None:
            tpl = tindex.get(key.lower() if standard else key)
            if tpl is None:
                stats.no_template += 1
                missing.append((key, run_text))
                continue
            ctx = _Run(gen, tags, vals, parents, mech_pos, suf_pos)
            block = []
            for seq, trow in enumerate(tpl.rows, start=1):
                derived = ctx.derived(seq)
                row = _expand_row(gen, ctx, trow.cells, derived, names, lower_names, tables, standard)
                if standard:
                    texts = [to_text(v) for v in row]
                    if any(DELETE_ROW.lower() in t.lower() for t in texts):
                        stats.deleted_rows += 1
                        continue
                    if any(MANUAL_ROW.lower() in t.lower() for t in texts):
                        warnings.append(Finding(severity="WARN", code="manualRow", item=f"run {run_text}",
                                                detail=f"template {tpl.id} row {seq} needs manual completion"))
                block.append(OutputRow(cells=[tpl.id_value, *row], run_row_id=rr.id, template_id=tpl.id, template_seq=seq))
        if out and cfg.blank_row_between_runs and block:
            out.append(OutputRow(cells=[None] * len(header)))
        out.extend(block)
        stats.processed += 1
    phase["expand"] = (time.perf_counter() - t1) * 1000

    t2 = time.perf_counter()
    found: dict[str, None] = {}
    count = 0
    non_empty = 0
    for r in out:
        for v in r.cells:
            if v is None or v == "":
                continue
            non_empty += 1
            if isinstance(v, str) and "<<" in v:
                for tok in TOKEN.findall(v):
                    if tok not in (NO_VALUE, PARENT_NOT_FOUND):
                        count += 1
                        found.setdefault(tok, None)
    stats.rows_written = sum(1 for r in out if r.run_row_id is not None)
    stats.output_rows = len(out)
    stats.non_empty_cells = non_empty
    if missing:
        listed = ", ".join(f"{k} (run {r})" for k, r in missing[:60])
        more = f" and {len(missing) - 60} more" if len(missing) > 60 else ""
        warnings.append(Finding(severity="WARN", code="missingTemplate", item=f"{len(missing)} runs without a template",
                                detail=listed + more))
    if dup_ids:
        warnings.append(Finding(severity="WARN", code="duplicateTemplateIds", item=", ".join(dup_ids),
                                detail="template ID used by more than one block; the first block is used"))
    if parents.duplicates:
        warnings.append(Finding(severity="WARN", code="duplicateParents", item=f"{len(parents.duplicates)} duplicate tags",
                                detail=", ".join(parents.duplicates[:20])))
    if count:
        warnings.append(Finding(severity="WARN", code="unresolvedTokens", item=f"{count} unresolved tokens",
                                detail=", ".join(list(found)[:12])))
    phase["scan"] = (time.perf_counter() - t2) * 1000

    changes = None
    if previous is not None and cfg.keep_prev:
        t3 = time.perf_counter()
        changes = change_report(previous.header, previous.rows, header, out, cfg.diff_key)
        phase["diff"] = (time.perf_counter() - t3) * 1000
    stats.duration_ms = (time.perf_counter() - t0) * 1000
    stats.phase_ms = phase
    if run_col is None and locked_pos is not None:
        warnings.append(Finding(severity="WARN", code="noRunColumn", item=cfg.run_column,
                                detail="RunColumn is not an output column, so locked runs cannot be matched"))
    return BuildResult(header=header, rows=out, stats=stats, warnings=warnings, unresolved_tokens=list(found)[:12],
                       unresolved_count=count, changes=changes, engine_version=ENGINE_VERSION)


def _expand_row(gen: Generator, ctx: _Run, cells: list[TemplateCell], derived, names: list[str],
                lower_names: dict[str, int], tables: dict[str, TableIndex], standard: bool) -> list[Scalar]:
    cfg = gen.config
    n = len(names)
    row: list[Scalar] = [None] * n
    formula = [False] * n
    pending: dict[int, object] = {}
    for i in range(n):
        c = cells[i] if i < len(cells) else None
        if c is None:
            continue
        if c.kind == "computed":
            comp = c.override or gen.output_columns[i].computed
            if comp is None:
                raise BuildError("computed columns", f"column '{names[i]}' is marked computed but has no definition")
            pending[i] = comp
            continue
        if gen.output_columns[i].raw:
            row[i] = c.text if c.text is not None else c.value
            continue
        if c.kind == "literal":
            v = c.value
            if isinstance(v, str) and _needs_expand(v, cfg):
                row[i], formula[i] = _write(ctx.expand(v, derived), standard)
            else:
                row[i] = v
        else:  # text, late, or an unmapped formula
            s = c.text if c.text is not None else to_text(c.value)
            row[i], formula[i] = _write(ctx.expand(s, derived), standard)

    if pending:
        state: dict[int, int] = {}  # 1 = evaluating, 2 = done

        def value(name: str) -> Scalar:
            j = lower_names.get(name.lower())
            if j is None:
                return NA
            if j in pending and state.get(j) != 2:
                if state.get(j) == 1:
                    return "#REF!"  # circular reference
                state[j] = 1
                row[j] = evaluate_computed(pending[j], value, tables, standard)
                formula[j] = True
                state[j] = 2
            return row[j]

        for i in pending:
            value(names[i])

    if cfg.freeze_formulas:  # PRD 5.9: formula values are expanded again
        for i in range(n):
            v = row[i]
            if formula[i] and isinstance(v, str) and not is_error(v) and _needs_expand(v, cfg):
                s = ctx.expand(v, derived)
                row[i] = as_typed(s) if not s.startswith("=") else _write(s, standard)[0]
    return row


def text_of_cell(c: TemplateCell) -> str:
    return c.text if c.text is not None else to_text(c.value)


def uses_tag(s: str, tag: str) -> bool:
    return contains_ci(s, tag[:-2])
