# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Check (PRD section 8): validation findings C1..C20 and the template index."""

from __future__ import annotations

import re
from collections import Counter, defaultdict

from pydantic import BaseModel, Field

from .computed import TableIndex, dependencies
from .expand import TOKEN, Parents, _Run, build, discover_tags, find_tag, template_index
from .expr import parses
from .models import BuildError, Finding, Generator, Lookup, Exists, Count
from .text import NO_VALUE, PARENT_NOT_FOUND, to_text

LOOP = re.compile(r"<<#(\d+)(?:_S|_P)?>>", re.IGNORECASE)


class TemplateIndexEntry(BaseModel):
    id: str
    rows: int
    runs: int  # runs on the runsheet (in range) using it
    used: bool


class CheckResult(BaseModel):
    findings: list[Finding] = Field(default_factory=list)
    template_index: list[TemplateIndexEntry] = Field(default_factory=list)

    @property
    def errors(self) -> int:
        return sum(1 for f in self.findings if f.severity == "ERROR")


def _template_strings(gen: Generator):
    """(template id, template row seq, column name, text) for every text-bearing cell."""
    names = [c.name for c in gen.output_columns]
    for t in gen.templates:
        for seq, tr in enumerate(t.rows, start=1):
            for j, c in enumerate(tr.cells):
                s = c.text if c.text is not None else (c.value if isinstance(c.value, str) else None)
                if s:
                    yield t.id, seq, names[j] if j < len(names) else f"#{j + 1}", s


def check(gen: Generator, cards: set[str] | None = None) -> CheckResult:
    res = CheckResult()
    F = res.findings
    cfg = gen.config
    standard = cfg.mode == "standard"

    def add(sev, code, item, detail="", where=""):
        F.append(Finding(severity=sev, code=code, item=str(item), detail=detail, where=where))

    try:
        tags = discover_tags(gen)
    except BuildError as exc:
        add("ERROR", "C2" if "duplicate" in str(exc) else "C1", "Tag row", str(exc), "RunSheet row 2")
        return res
    tag_low = {t.lower(): pos for pos, t in tags}
    key_pos = find_tag(tags, cfg.key_placeholder)
    if key_pos is None:
        key_pos = tags[0][0]
    run_pos = find_tag(tags, cfg.run_placeholder)
    locked_pos = find_tag(tags, cfg.locked_placeholder)
    parents = Parents(gen.parents if cfg.use_parents else None, cfg.parent_include_tag, standard)
    tindex, _ = template_index(gen, standard)

    # C3 duplicate template blocks
    blocks = Counter(t.id for t in gen.templates)
    for tid, n in blocks.items():
        extra = next((t.duplicate_blocks for t in gen.templates if t.id == tid), 0)
        if n > 1 or extra:
            add("ERROR", "C3", f"Template {tid}", f"appears in {max(n, extra + 1)} separate blocks; the first block is used", "Templates")

    # C4 / C5 tokens used by templates
    derived = {(d.name if d.name.startswith("<<") else f"<<{d.name}>>").lower() for d in gen.derived_tags}
    known = set(tag_low) | derived | {"<<parent>>", NO_VALUE.lower(), PARENT_NOT_FOUND.lower()}
    for t in list(tag_low):
        known.add(t[:-2] + "_s>>")
        known.add(t[:-2] + "_p>>")
    unknown: dict[str, set[str]] = defaultdict(set)
    parent_uses: dict[str, set[str]] = defaultdict(set)  # tag -> templates using its _P
    uses_parent: set[str] = set()
    used_tags: set[str] = set()
    loops: dict[str, set[int]] = defaultdict(set)
    for tid, _seq, _col, s in _template_strings(gen):
        for tok in TOKEN.findall(s):
            tl = tok.lower()
            if tl not in known:
                unknown[tok].add(tid)
                continue
            if tl == "<<parent>>":
                uses_parent.add(tid)
            elif tl.endswith("_p>>") and tl not in tag_low:
                parent_uses[tl[:-4] + ">>"].add(tid)
            base = tl[:-4] + ">>" if (tl.endswith("_s>>") or tl.endswith("_p>>")) and tl not in tag_low else tl
            used_tags.add(base)
        for m in LOOP.finditer(s):
            loops[tid].add(int(m.group(1)))
    for tok, tids in sorted(unknown.items()):
        add("ERROR", "C4", tok, f"used by template(s) {', '.join(sorted(tids)[:10])} but it is not a runsheet tag, a _S/_P form, a derived tag or <<PARENT>>", "Templates")
    if not parents.present and (parent_uses or uses_parent):
        add("ERROR", "C5", "Parents", "templates use _P or <<PARENT>> but there is no Parents table", "Config ParentSheet")
    if uses_parent and (find_tag(tags, "<<MECH>>") is None or find_tag(tags, "<<SUF>>") is None):
        add("ERROR", "C5", "<<PARENT>>", "templates use <<PARENT>> but the runsheet has no <<MECH>> / <<SUF>> columns")

    # runsheet rows
    rng_from, rng_to = cfg.run_from, cfg.run_up_to
    runs_seen: dict[str, list[str]] = defaultdict(list)
    missing: list[str] = []
    used_templates: Counter = Counter()
    parent_missing: dict[str, set[str]] = defaultdict(set)
    loop_blank: list[str] = []
    scope_pos = find_tag(tags, "<<Scope>>")
    scope_map: dict[str, Counter] = defaultdict(Counter)
    mech_pos = find_tag(tags, "<<MECH>>")
    for rr in gen.runsheet.rows:
        v = rr.values
        key = to_text(v[key_pos] if key_pos < len(v) else None)
        has_data = any(to_text(x).strip() for x in v)
        if key.strip() == "":
            if has_data:
                add("WARN", "C11", f"row {rr.id}", "row has data but no key", f"RunSheet row {rr.id}")
            continue
        if key.strip().lower() in ("nr", "none"):
            continue
        run_text = to_text(v[run_pos]) if run_pos is not None and run_pos < len(v) else ""
        if run_pos is not None:
            if run_text.strip() == "":
                add("WARN", "C7", f"row {rr.id}", "run number is blank", f"RunSheet row {rr.id}")
            else:
                runs_seen[run_text].append(rr.id)
                try:
                    run = float(run_text)
                except ValueError:
                    run = 0.0
                    if standard:
                        add("ERROR", "C7", f"row {rr.id}", f"run number '{run_text}' is not a number", f"RunSheet row {rr.id}")
                if (rng_from is not None and run < rng_from) or (rng_to is not None and run >= rng_to):
                    continue
        if scope_pos is not None:
            scope_map[key][to_text(v[scope_pos] if scope_pos < len(v) else None)] += 1
        tpl = tindex.get(key.lower() if standard else key)
        if tpl is None:
            missing.append(f"{key} (run {run_text})")
            continue
        used_templates[tpl.id] += 1
        for tag in parent_uses:
            pos = tag_low.get(tag)
            if pos is not None:
                val = to_text(v[pos] if pos < len(v) else None)
                if val and not parents.lookup(val)[0]:
                    parent_missing[val].add(run_text)
        if tpl.id in uses_parent and mech_pos is not None and parents.present:
            val = to_text(v[mech_pos] if mech_pos < len(v) else None)
            if val and not parents.lookup(val)[0]:
                parent_missing[val].add(run_text)
        for n in sorted(loops.get(tpl.id, ())):
            pos = tag_low.get(f"<<#{n}>>")
            if pos is not None and to_text(v[pos] if pos < len(v) else None).strip() == "":
                loop_blank.append(f"run {run_text}: <<#{n}>>")
    if missing:
        more = f" ... and {len(missing) - 60} more" if len(missing) > 60 else ""
        add("ERROR", "C6", f"{len(missing)} run{'' if len(missing) == 1 else 's'} without a template", ", ".join(missing[:60]) + more, "RunSheet")
    for run, rows in runs_seen.items():
        if len(rows) > 1:
            add("WARN", "C8", f"run {run}", f"used on rows {', '.join(rows[:10])}", "RunSheet")
    for tag, runs in sorted(parent_missing.items()):
        add("WARN", "C9", tag, f"not found on Parents (runs {', '.join(sorted(runs)[:10])})", "Parents")
    if parents.duplicates:
        add("WARN", "C10", f"{len(parents.duplicates)} duplicate tags on Parents", ", ".join(parents.duplicates[:30]), "Parents")
    special = {cfg.key_placeholder.lower(), cfg.run_placeholder.lower(), cfg.locked_placeholder.lower()}
    for pos, t in tags:
        if t.lower() not in used_tags and t.lower() not in special and pos != locked_pos:
            if t.lower() in ("<<mech>>", "<<suf>>") and uses_parent:
                continue
            add("INFO", "C12", t, "runsheet tag not used by any template", "RunSheet")
    seen_ids = set()
    for t in gen.templates:
        if t.id in seen_ids:
            continue
        seen_ids.add(t.id)
        res.template_index.append(TemplateIndexEntry(id=t.id, rows=len(t.rows), runs=used_templates[t.id],
                                                     used=used_templates[t.id] > 0))
        if not used_templates[t.id]:
            add("INFO", "C13", f"Template {t.id}", "not used on the runsheet (in the run range)", "Templates")
    if loop_blank:
        add("WARN", "C19", f"{len(loop_blank)} loop numbers blank", "; ".join(loop_blank[:40]), "RunSheet")

    # C14 key <-> scope (Power)
    for key, c in scope_map.items():
        if len(c) > 1:
            main, n = c.most_common(1)[0]
            others = ", ".join(f"{s or '(blank)'} x{k}" for s, k in c.items() if s != main)
            add("WARN", "C14", f"key {key}", f"mostly {main} ({n} runs) but also {others}", "RunSheet <<Scope>>")

    # C15 lookup keys written raw (keys that are tag patterns) must exist in their table
    names = [c.name for c in gen.output_columns]
    all_defs = [c.computed for c in gen.output_columns if c.computed is not None]
    all_defs += [cell.override for t in gen.templates for tr in t.rows for cell in tr.cells if cell.override is not None]
    for j, oc in enumerate(gen.output_columns):
        if not oc.raw:
            continue
        lk = next((d for d in all_defs if isinstance(d, Lookup) and d.key.lower() == oc.name.lower()), None)
        if lk is None or lk.table not in gen.tables:
            continue
        idx = TableIndex(gen.tables[lk.table])
        for t in gen.templates:
            for seq, tr in enumerate(t.rows, start=1):
                c = tr.cells[j] if j < len(tr.cells) else None
                s = (c.text or to_text(c.value)) if c else ""
                try:
                    missing = s and idx.find(lk.key_column, s) is None
                except KeyError:
                    missing = False  # reported by C17
                if missing:
                    add("ERROR", "C15", s, f"{oc.name} of template {t.id} row {seq} is not a key of {lk.table}", "Templates")

    # C16 card types, when a card catalogue is given
    if cards and "CARD TYPE" in names:
        j = names.index("CARD TYPE")
        bad: dict[str, set[str]] = defaultdict(set)
        for t in gen.templates:
            for tr in t.rows:
                c = tr.cells[j] if j < len(tr.cells) else None
                s = to_text(c.text or c.value).strip() if c else ""
                if s and s not in cards:
                    bad[s].add(t.id)
        for s, tids in bad.items():
            add("ERROR", "C16", s, f"card type not in the catalogue (templates {', '.join(sorted(tids)[:10])})", "Templates CARD TYPE")

    # C17 computed column references
    lower_names = {n.lower() for n in names}
    defs = [(c.name, c.computed) for c in gen.output_columns if c.computed is not None]
    defs += [(names[j], cell.override) for t in gen.templates for tr in t.rows
             for j, cell in enumerate(tr.cells) if cell.override is not None and j < len(names)]
    seen_defs = set()
    for col, d in defs:
        sig = (col, d.model_dump_json())
        if sig in seen_defs:
            continue
        seen_defs.add(sig)
        for ref in dependencies(d):
            if ref.lower() not in lower_names:
                add("ERROR", "C17", col, f"references missing output column '{ref}'", "computed columns")
        if isinstance(d, (Lookup, Exists, Count)):
            t = gen.tables.get(d.table)
            if t is None:
                add("ERROR", "C17", col, f"references missing table '{d.table}'", "computed columns")
                continue
            cols = {c.lower() for c in t.columns}
            for need in ([d.key_column, d.return_column] if isinstance(d, Lookup) else [d.column]):
                if need.lower() not in cols:
                    add("ERROR", "C17", col, f"table '{d.table}' has no column '{need}'", "computed columns")

    # C18 late formulas parse after a sample expansion
    sample: dict[str, list] = {}
    for rr in gen.runsheet.rows:
        k = to_text(rr.values[key_pos] if key_pos < len(rr.values) else None)
        tpl = tindex.get(k.lower() if standard else k)
        if tpl is not None and tpl.id not in sample:
            sample[tpl.id] = rr.values
    mpos, spos = find_tag(tags, "<<MECH>>"), find_tag(tags, "<<SUF>>")
    for t in gen.templates:
        for seq, tr in enumerate(t.rows, start=1):
            for j, c in enumerate(tr.cells):
                if c.kind != "late" or not c.text:
                    continue
                if t.id in sample:
                    ctx = _Run(gen, tags, sample[t.id], parents, mpos, spos)
                    s = ctx.expand(c.text, ctx.derived(seq))
                else:
                    s = TOKEN.sub("1", c.text)
                s = s.replace("F=", "=", 1) if s.startswith("F=") else s
                if s.startswith("=") and cfg.replace_f_equals and not parses(s):
                    add("ERROR", "C18", f"template {t.id} row {seq}", f"'{c.text}' does not parse after expansion: {s}",
                        f"Templates column '{names[j] if j < len(names) else j}'")

    # C20 duplicate generated keys (needs the output)
    try:
        out = build(gen)
    except BuildError as exc:
        add("ERROR", "BUILD", "build", str(exc))
        return res
    key_col = cfg.diff_key
    hl = [h.lower() for h in out.header]
    if key_col.lower() in hl:
        ki = hl.index(key_col.lower())
        cnt = Counter(to_text(r.cells[ki]) for r in out.rows if r.run_row_id is not None)
        dups = [k for k, n in cnt.items() if n > 1 and k and NO_VALUE not in k]
        if dups:
            add("ERROR", "C20", f"{len(dups)} {key_col} values produced more than once",
                ", ".join(sorted(dups)[:40]) + (" ..." if len(dups) > 40 else ""), f"Output column '{key_col}'")
    return res
