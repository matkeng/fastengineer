# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Import a generator workbook (.xlsm/.xlsx) into a Generator (PRD 14.1).

Runsheet values are the cached (calculated) values; template formulas are mapped to
declarative computed columns where they match a known pattern (PRD 7.1) and flagged
otherwise. The import never fixes data: it reports what it found (PRD 19)."""

from __future__ import annotations

import re
import warnings
from collections import Counter
from pathlib import Path

from pydantic import BaseModel, Field

from .models import (CablePrefix, ColumnDef, Computed, Concat, Count, DerivedTag, Exists, Generator,
                     GeneratorConfig, Lookup, OutputColumn, RefTable, Route, RunRow, Runsheet, Scalar,
                     Template, TemplateCell, TemplateRow, DEFAULT_CONFIGS)
from .text import to_text

#: The row number of a cell reference in a formula (A5, $B12): the column is kept. Not the digits
#: of a function's name (LOG10(, ATAN2().
_ROW_OF_REF = re.compile(r"(?<![A-Za-z0-9_.])([A-Z]{1,3})\d+\b(?!\()")
SOURCE_WORDS = {"model", "number", "choice", "inbuilt", "builtin", "text"}


class UnmappedFormula(BaseModel):
    where: str
    formula: str
    count: int = 1


class ImportReport(BaseModel):
    workbook: str
    generator: str
    runsheet_rows: int = 0
    tags: int = 0
    templates: int = 0
    template_rows: int = 0
    duplicate_template_ids: list[str] = Field(default_factory=list)
    mapped_formulas: dict[str, int] = Field(default_factory=dict)  # pattern -> count
    unmapped_formulas: list[UnmappedFormula] = Field(default_factory=list)
    runsheet_formula_columns: dict[str, str] = Field(default_factory=dict)  # tag -> formula (values cached)
    parents: int = 0
    tables: dict[str, int] = Field(default_factory=dict)  # table -> rows
    baseline_rows: int = 0
    issues: list[str] = Field(default_factory=list)


class ImportResult(BaseModel):
    generator: Generator
    report: ImportReport
    baseline_header: list[str] | None = None
    baseline_rows: list[list[Scalar]] | None = None


def _load(source: Path | bytes):
    import io

    import openpyxl
    src = (lambda: io.BytesIO(source)) if isinstance(source, (bytes, bytearray)) else (lambda: source)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            wb_f = openpyxl.load_workbook(src(), data_only=False, keep_vba=False)
            wb_v = openpyxl.load_workbook(src(), data_only=True, keep_vba=False)
        except Exception as exc:  # noqa: BLE001 - zip / xml errors from a file that is not a workbook
            raise ValueError(f"Not an Excel workbook (.xlsx/.xlsm): {exc}") from exc
    return wb_f, wb_v


def _find_table(wb, name: str):
    for ws in wb.worksheets:
        if name in ws.tables:
            return ws, ws.tables[name]
    return None, None


def _bounds(ref: str) -> tuple[int, int, int, int]:
    from openpyxl.utils.cell import range_boundaries
    c1, r1, c2, r2 = range_boundaries(ref)
    return c1, r1, c2, r2


def _rows(ws, r1: int, r2: int, c1: int, c2: int) -> list[list[Scalar]]:
    return [list(r) for r in ws.iter_rows(min_row=r1, max_row=r2, min_col=c1, max_col=c2, values_only=True)]


def _clean(v: Scalar) -> Scalar:
    """openpyxl returns whole floats as int already; normalise datetimes that are dates."""
    from datetime import datetime
    if isinstance(v, datetime) and not (v.hour or v.minute or v.second or v.microsecond):
        return v.date()
    return v


def _bool(s: str) -> bool:
    return str(s).strip().lower() in ("true", "yes", "1", "y")


def _num_or_none(s: str) -> float | None:
    s = str(s or "").strip()
    if s == "":
        return None
    try:
        f = float(s)
    except ValueError:
        return None
    return int(f) if f == int(f) else f


def guess_generator(path: Path, title: str) -> str:
    t = f"{path.name} {title}".lower()
    if "device" in t:
        return "deviceList"
    if "io list" in t or "io_list" in t or "plc" in t:
        return "ioList"
    if "instrument" in t:
        return "instCable"
    if "power" in t:
        return "power"
    if "dp" in t:
        return "dp"
    return "dp"


def read_config(wb, gen_id: str) -> tuple[GeneratorConfig, dict[str, str]]:
    ws, t = _find_table(wb, "tblConfig")
    raw: dict[str, str] = {}
    if t is not None:
        c1, r1, c2, r2 = _bounds(t.ref)
        for row in _rows(ws, r1 + 1, r2, c1, c1 + 1):
            if row[0] is not None:
                raw[str(row[0]).strip()] = "" if row[1] is None else str(row[1])
    cfg = DEFAULT_CONFIGS.get(gen_id, GeneratorConfig()).model_copy(deep=True)
    known = {
        "KeyPlaceholder": ("key_placeholder", str), "RunPlaceholder": ("run_placeholder", str),
        "LockedPlaceholder": ("locked_placeholder", str), "StopAtBlankKey": ("stop_at_blank_key", _bool),
        "BlankRowBetweenRuns": ("blank_row_between_runs", _bool), "ParentIncludeTag": ("parent_include_tag", _bool),
        "CollapseSpaces": ("collapse_spaces", _bool), "ReplaceFEquals": ("replace_f_equals", _bool),
        "FreezeFormulas": ("freeze_formulas", _bool), "RunFrom": ("run_from", _num_or_none),
        "RunUpTo": ("run_up_to", _num_or_none), "KeepPrev": ("keep_prev", _bool), "DiffKey": ("diff_key", str),
        "RunColumn": ("run_column", str), "DocNumber": ("doc_number", str), "DocTitle": ("doc_title", str),
        "DocRevision": ("doc_revision", str),
    }
    extra = {}
    for k, v in raw.items():
        if k in known:
            attr, conv = known[k]
            setattr(cfg, attr, conv(v))
        else:
            extra[k] = v
    if "ParentSheet" in raw:
        cfg.use_parents = raw["ParentSheet"].strip() != ""
    cfg.extra = extra
    return cfg, raw


# -- formula mapping (PRD 7.1) ---------------------------------------------------------

_SHEET = r"(?:'(?P<{n}q>[^']+)'|(?P<{n}>[A-Za-z_][\w .]*))!"


def _sheet_re(n: str) -> str:
    return _SHEET.format(n=n)


def _sheet(m: re.Match, n: str) -> str:
    return m.group(n + "q") or m.group(n)


class FormulaMapper:
    """Maps a template formula (row-relative) to a computed column definition."""

    def __init__(self, header: list[str], first_col: int):
        from openpyxl.utils import column_index_from_string, get_column_letter
        self.header, self.first_col = header, first_col
        self.ci, self.letter = column_index_from_string, get_column_letter
        self.tables: set[str] = set()

    def colname(self, letter: str) -> str | None:
        i = self.ci(letter) - self.first_col
        if 1 <= i < len(self.header):
            return self.header[i]
        return None

    def _offset(self, letter: str, n: int) -> str:
        return self.letter(self.ci(letter) + n - 1)

    def map(self, formula: str, row: int) -> tuple[str, Computed] | None:
        f = formula.strip().replace("$", "")
        rx = rf"([A-Z]{{1,3}}){row}(?![0-9])"
        ref = lambda s: re.fullmatch(rx, s.strip())  # noqa: E731
        body = f[1:].strip()

        m = re.fullmatch(rf"EXACT\(VLOOKUP\(([A-Z]{{1,3}}){row},{_sheet_re('s')}([A-Z]{{1,3}}):([A-Z]{{1,3}}),1\),([A-Z]{{1,3}}){row}\)", body)
        if m and m.group(1) == m.group(len(m.groups())):
            col = self.colname(m.group(1))
            if col:
                t = _sheet(m, "s")
                self.tables.add(t)
                return "exists (EXACT/VLOOKUP approximate)", Exists(value=col, table=t, column=m.group(4))

        vl = rf"VLOOKUP\(([A-Z]{{1,3}}){row},{_sheet_re('s')}([A-Z]{{1,3}}):([A-Z]{{1,3}}),(\d+),(?:0|FALSE)\)"
        m = re.fullmatch(vl, body)
        guard = None
        kind = "lookup (VLOOKUP)"
        if not m:
            m2 = re.fullmatch(rf'IF\(([A-Z]{{1,3}}){row}<>"",{vl},""\)', body) or \
                re.fullmatch(rf'IF\(([A-Z]{{1,3}}){row}="","",{vl}\)', body)
            if m2:
                guard = m2.group(1)
                m = re.fullmatch(vl, re.search(vl, body).group(0))
                kind = "lookup (IF blank, VLOOKUP)"
        if m:
            key, t, a = self.colname(m.group(1)), _sheet(m, "s"), m.group(4)
            n = int(m.group(6))
            if key and (guard is None or self.colname(guard)):
                self.tables.add(t)
                return kind, Lookup(key=key, table=t, key_column=a, return_column=self._offset(a, n),
                                    guard_column=self.colname(guard) if guard else None)

        m = re.fullmatch(rf"COUNTIF\({_sheet_re('s')}([A-Z]{{1,3}}):([A-Z]{{1,3}}),([A-Z]{{1,3}}){row}\)", body)
        if m and self.colname(m.group(5)):
            t = _sheet(m, "s")
            self.tables.add(t)
            return "count (COUNTIF)", Count(table=t, column=m.group(3), equals=self.colname(m.group(5)))

        parts = _split_concat(body)
        if parts and len(parts) > 1:
            out: list = []
            for p in parts:
                if p.startswith('"') and p.endswith('"') and len(p) >= 2:
                    out.append(p[1:-1].replace('""', '"'))
                elif ref(p) and self.colname(ref(p).group(1)):
                    out.append({"col": self.colname(ref(p).group(1))})
                else:
                    return None
            return "concat (&)", Concat(parts=out)
        return None


def _split_concat(body: str) -> list[str]:
    parts, cur, q = [], [], False
    for ch in body:
        if ch == '"':
            q = not q
        if ch == "&" and not q:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur).strip())
    return parts


def _sheet_table(wb_v, name: str) -> RefTable | None:
    """A whole sheet as a lookup table, columns named by letter (VLOOKUP over B:I etc.)."""
    if name not in wb_v.sheetnames:
        return None
    from openpyxl.utils import get_column_letter
    ws = wb_v[name]
    rows = [[_clean(v) for v in r] for r in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=1,
                                                       max_col=ws.max_column, values_only=True)]
    while rows and all(v is None for v in rows[-1]):
        rows.pop()
    cols = [get_column_letter(i + 1) for i in range(ws.max_column)]
    return RefTable(name=name, columns=cols, rows=rows, first_column=1)


def import_workbook(source: str | Path | bytes, gen_id: str | None = None, filename: str | None = None) -> ImportResult:
    """Import from a path, or from the workbook's bytes (then give `filename`)."""
    import gc
    try:
        if isinstance(source, (bytes, bytearray)):
            return _import(bytes(source), Path(filename or "workbook.xlsx"), gen_id)
        return _import(Path(source), Path(source), gen_id)
    finally:
        gc.collect()  # openpyxl workbooks are reference cycles; free them now, not mid-build


def _import(source: Path | bytes, path: Path, gen_id: str | None) -> ImportResult:
    wb_f, wb_v = _load(source)
    title = ""
    ws_c, t_c = _find_table(wb_f, "tblConfig")
    if t_c is not None:
        c1, r1, c2, r2 = _bounds(t_c.ref)
        for row in _rows(ws_c, r1 + 1, r2, c1, c1 + 1):
            if str(row[0]).strip() == "DocTitle":
                title = str(row[1] or "")
    gid = gen_id or guess_generator(path, title)
    cfg, raw = read_config(wb_f, gid)
    rep = ImportReport(workbook=path.name, generator=gid)

    # -- runsheet -------------------------------------------------------------------
    ws, t = _find_table(wb_f, "tblRunSheet")
    if t is None:
        raise ValueError("tblRunSheet not found")
    c1, r1, c2, r2 = _bounds(t.ref)
    wsv = wb_v[ws.title]
    tag_row = _rows(ws, r1, r1, c1, c2)[0]
    label_row = _rows(ws, r1 - 1, r1 - 1, c1, c2)[0] if r1 > 1 else [None] * len(tag_row)
    cols = [ColumnDef(name=str(label_row[i]) if label_row[i] is not None else str(tag_row[i] or ""),
                      tag=str(tag_row[i]).strip() if tag_row[i] is not None else None)
            for i in range(len(tag_row))]
    vals = _rows(wsv, r1 + 1, r2, c1, c2)
    forms = _rows(ws, r1 + 1, r2, c1, c2)
    start = 0
    if vals:  # Power: an annotations row (Model / Number / Choice / Inbuilt) heads the data
        first = [str(v).strip().lower() for v in vals[0] if v not in (None, "")]
        if first and all(w in SOURCE_WORDS for w in first):
            for i, v in enumerate(vals[0]):
                if v not in (None, ""):
                    cols[i].source = "builtin" if str(v).strip().lower() == "inbuilt" else str(v).strip().lower()
            start = 1
    for i in range(len(cols)):
        for fr in forms[start:]:
            v = fr[i] if i < len(fr) else None
            if isinstance(v, str) and v.startswith("="):
                cols[i].formula = _ROW_OF_REF.sub(r"\1{row}", v)
                rep.runsheet_formula_columns[cols[i].tag or cols[i].name] = cols[i].formula
                break
    rows = [RunRow(id=str(r1 + 1 + k), values=[_clean(v) for v in vals[k]]) for k in range(start, len(vals))]
    runsheet = Runsheet(columns=cols, rows=rows)
    rep.runsheet_rows = len(rows)
    rep.tags = sum(1 for c in cols if c.tag and c.tag.startswith("<<") and c.tag.endswith(">>"))

    # -- templates --------------------------------------------------------------------
    ws, t = _find_table(wb_f, "tblTemplates")
    if t is None:
        raise ValueError("tblTemplates not found")
    c1, r1, c2, r2 = _bounds(t.ref)
    head = [("" if v is None else str(v)) for v in _rows(ws, r1, r1, c1, c2)[0]]
    trows = _rows(ws, r1 + 1, r2, c1, c2)
    mapper = FormulaMapper(head, c1)
    out_cols = [OutputColumn(name=h) for h in head[1:]]
    col_defs: dict[int, list[tuple[str, Computed]]] = {}
    unmapped: Counter = Counter()
    mapped: Counter = Counter()
    blocks: list[tuple[str, Scalar, list[TemplateRow]]] = []
    for k, r in enumerate(trows):
        sheet_row = r1 + 1 + k
        idv = r[0]
        if idv is None or to_text(idv).strip() == "":
            continue
        cells = []
        for j, v in enumerate(r[1:], start=1):
            if isinstance(v, str) and v.startswith("=") and len(v) > 1:
                m = mapper.map(v, sheet_row)
                if m:
                    mapped[m[0]] += 1
                    col_defs.setdefault(j - 1, []).append(m)
                    cells.append(TemplateCell(kind="computed", override=m[1]))
                else:
                    unmapped[(head[j], re.sub(rf"(?<=[A-Z]){sheet_row}\b", "{row}", v))] += 1
                    cells.append(TemplateCell(kind="formula", text=v))
            elif isinstance(v, str) and "F=" in v:
                cells.append(TemplateCell(kind="late", text=v))
            elif isinstance(v, str) and "<<" in v:
                cells.append(TemplateCell(kind="text", text=v))
            else:
                cells.append(TemplateCell(kind="literal", value=_clean(v)))
        tid = to_text(idv)
        if blocks and blocks[-1][0] == tid:
            blocks[-1][2].append(TemplateRow(cells=cells, source_row=sheet_row))
        else:
            blocks.append((tid, idv, [TemplateRow(cells=cells, source_row=sheet_row)]))
    # one definition per column where every row agrees; keep per-row overrides otherwise
    for j, defs in col_defs.items():
        first = defs[0][1]
        if all(d[1] == first for d in defs):
            out_cols[j].computed = first
    templates: list[Template] = []
    seen: dict[str, Template] = {}
    for tid, idv, trs in blocks:
        for tr in trs:
            for j, c in enumerate(tr.cells):
                if c.kind == "computed" and out_cols[j].computed is not None and c.override == out_cols[j].computed:
                    c.override = None
        if tid in seen:
            seen[tid].duplicate_blocks += 1
            if tid not in rep.duplicate_template_ids:
                rep.duplicate_template_ids.append(tid)
            templates.append(Template(id=tid, id_value=idv, rows=trs))  # kept for Check, ignored by build
            continue
        tpl = Template(id=tid, id_value=idv, rows=trs)
        seen[tid] = tpl
        templates.append(tpl)
    rep.templates = len(seen)
    rep.template_rows = sum(len(t.rows) for t in seen.values())
    rep.mapped_formulas = dict(mapped)
    rep.unmapped_formulas = [UnmappedFormula(where=f"Templates column '{c}'", formula=f, count=n)
                             for (c, f), n in unmapped.most_common()]
    dup_heads = [h for h, n in Counter(h.lower() for h in head[1:] if h).items() if n > 1]
    if dup_heads:
        rep.issues.append(f"Template header repeats column names: {', '.join(dup_heads)} (references use the first)")

    # -- parents ----------------------------------------------------------------------
    parents = None
    if cfg.use_parents:
        sheet = raw.get("ParentSheet", "Parents").strip() or "Parents"
        if sheet in wb_f.sheetnames:
            pws = wb_f[sheet]
            pv = wb_v[sheet]
            if pws.tables:
                pt = next(iter(pws.tables.values()))
                c1, r1, c2, r2 = _bounds(pt.ref)
                prs = _rows(pv, r1 + 1, r2, c1, c1 + 1)
            else:
                tc = int(raw.get("ParentTagCol", "2") or 2)
                prs = _rows(pv, 2, pv.max_row, tc, tc + 1)
            parents = [(to_text(a), to_text(b)) for a, b in prs if a not in (None, "")]
            rep.parents = len(parents)
        else:
            rep.issues.append(f"Parents sheet '{sheet}' not found")

    # -- derived tags, routes, prefixes -----------------------------------------------
    derived, routes, prefixes = [], [], []
    for name, sink in (("tblPlaceholders", derived), ("tblRoutes", routes), ("tblCablePrefix", prefixes)):
        ws, t = _find_table(wb_f, name)
        if t is None:
            continue
        c1, r1, c2, r2 = _bounds(t.ref)
        for r in _rows(wb_v[ws.title], r1 + 1, r2, c1, c2):
            if name == "tblPlaceholders" and r[0] not in (None, ""):
                derived.append(DerivedTag(name=str(r[0]), source=to_text(r[1]), transform=to_text(r[2]),
                                          default=to_text(r[3]) if len(r) > 3 else ""))
            elif name == "tblRoutes" and r[0] not in (None, "") and r[1] not in (None, "") and isinstance(r[2], (int, float)):
                routes.append(Route(a=str(r[0]), b=str(r[1]), length=float(r[2])))
            elif name == "tblCablePrefix" and r[0] not in (None, "") and r[1] not in (None, ""):
                prefixes.append(CablePrefix(cable_type=str(r[0]), prefix=str(r[1])))

    # -- lookup tables used by computed columns ---------------------------------------
    tables: dict[str, RefTable] = {}
    for name in sorted(mapper.tables):
        rt = _sheet_table(wb_v, name)
        if rt is None:
            rep.issues.append(f"Lookup sheet '{name}' referenced by a formula is missing")
            continue
        tables[name] = rt
        rep.tables[name] = len(rt.rows)
    # a lookup whose table keys hold tag patterns needs its key column written unexpanded
    lookups = [(d, j) for j, defs in col_defs.items() for _, d in defs if isinstance(d, Lookup)]
    for d, _j in lookups:
        t = tables.get(d.table)
        if t is None:
            continue
        ki = t.columns.index(d.key_column) if d.key_column in t.columns else None
        if ki is None:
            continue
        keys = [to_text(r[ki]) for r in t.rows if ki < len(r) and r[ki] not in (None, "")]
        if any("<<" in k for k in keys):
            names = [c.name for c in out_cols]
            if d.key in names and not out_cols[names.index(d.key)].raw:
                out_cols[names.index(d.key)].raw = True
                rep.issues.append(f"'{d.key}' holds keys of {d.table} (tag patterns): written without expansion")
    for name in sorted({d.table for d, _ in lookups}):
        t = tables.get(name)
        if t is None:
            continue
        key_cols = {d.key_column for d, _ in lookups if d.table == name}
        for kc in sorted(key_cols):
            ki = t.columns.index(kc) if kc in t.columns else None
            if ki is None:
                continue
            keys = [to_text(r[ki]) for r in t.rows[1:] if ki < len(r) and r[ki] not in (None, "")]
            dups = [k for k, n in Counter(keys).items() if n > 1]
            if dups:
                rep.issues.append(f"{name} column {kc} has duplicate lookup keys: {', '.join(dups[:20])}")

    gen = Generator(id=gid, name=cfg.doc_title or gid, config=cfg, runsheet=runsheet, id_column=head[0] or "TEMPLATE",
                    output_columns=out_cols, templates=templates, derived_tags=derived, routes=routes,
                    cable_prefixes=prefixes, parents=parents, tables=tables)

    # -- baseline (Output / Output_prev) ----------------------------------------------
    res = ImportResult(generator=gen, report=rep)
    for sheet in ("Output", "Output_prev"):
        if sheet in wb_v.sheetnames:
            ows = wb_v[sheet]
            data = [list(r) for r in ows.iter_rows(min_row=1, max_row=ows.max_row, values_only=True)]
            if len(data) > 1 and any(v is not None for r in data[1:] for v in r):
                res.baseline_header = [to_text(v) for v in data[0]]
                res.baseline_rows = [[_clean(v) for v in r] for r in data[1:]]
                rep.baseline_rows = sum(1 for r in data[1:] if any(v not in (None, "") for v in r))
                break
    _data_issues(gen, rep)
    return res


def _data_issues(gen: Generator, rep: ImportReport) -> None:
    """PRD 19: surface known data problems (they are reported, never fixed)."""
    from .expand import discover_tags, find_tag
    try:
        tags = discover_tags(gen)
    except Exception as exc:  # noqa: BLE001
        rep.issues.append(str(exc))
        return
    if rep.duplicate_template_ids:
        rep.issues.append(f"Template IDs in more than one block: {', '.join(rep.duplicate_template_ids)}")
    for j, oc in enumerate(gen.output_columns):
        if not oc.raw:
            continue
        name = oc.name
        rows = [tr for t in gen.templates for tr in t.rows]
        blank = sum(1 for tr in rows if j >= len(tr.cells) or tr.cells[j].value in (None, "") and not tr.cells[j].text)
        if blank:
            rep.issues.append(f"'{name}' is blank on {blank} of {len(rows)} template rows")
    run_pos = find_tag(tags, gen.config.run_placeholder)
    key_pos = find_tag(tags, gen.config.key_placeholder) or tags[0][0]
    if run_pos is not None:
        runs = [to_text(r.values[run_pos]) for r in gen.runsheet.rows
                if run_pos < len(r.values) and to_text(r.values[key_pos] if key_pos < len(r.values) else None).strip()]
        dups = sorted({k for k, n in Counter(runs).items() if n > 1 and k}, key=lambda s: (len(s), s))
        if dups:
            rep.issues.append(f"Run numbers used more than once: {', '.join(dups[:30])}" + (" ..." if len(dups) > 30 else ""))
    for pos, tag in tags:
        vals = {to_text(r.values[pos]) for r in gen.runsheet.rows if pos < len(r.values)}
        markers = sorted(v for v in vals if "<<" in v)
        if markers:
            rep.issues.append(f"Runsheet column {tag} holds tag-like values: {', '.join(markers[:5])}")
