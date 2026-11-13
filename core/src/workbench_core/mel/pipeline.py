# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""The transformation pipeline (PRD section 6). Order is load-bearing:

  0 source     the latest revision's rows
  1 columns    hide / rename columns   (later rules use the new names)
  2 rows       hide rows by key
  3 text       constant columns        (before overrides, so they can be overridden)
  4 overrides  single-cell values
  5 custom     appended rows           (after overrides; before calculated columns)
  6 replace    find / replace columns: a new column of a column's values, whole values
               replaced (custom rows too; later ones can use earlier ones)
  7 auto       calculated columns, in order (see every other column)

Each editor shows the table after the stage before it, e.g. overrides edit
the output of stage 3.
"""

from __future__ import annotations

import math
import re
from typing import Literal

from asteval import Interpreter

from .functions import NotAllowed, make_interpreter, prepare
from pydantic import BaseModel, Field

from .models import NUMERIC_FIELDS, TARGET_BOOLEAN, TARGET_NUMERIC, Recipe, Revision, fields_for

Stage = Literal["source", "columns", "rows", "text", "overrides", "custom", "replace", "auto"]
STAGES: list[Stage] = ["source", "columns", "rows", "text", "overrides", "custom", "replace", "auto"]

REF = re.compile(r"""(["']?)<<(.+?)>>\1""")
NUMBER = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")


class PipelineRow(BaseModel):
    key: str
    origin: Literal["file", "custom"]
    file_row: int | None  # 1-based data row in the source file
    values: dict[str, str]
    overridden: list[str] = Field(default_factory=list)
    auto_errors: list[str] = Field(default_factory=list)


class RuleIssue(BaseModel):
    """A rule that no longer applies (e.g. its key or column isn't in the latest file)."""
    kind: str  # columns / rows / text / overrides / custom / replace / auto / mapping
    rule: str
    message: str


class PipelineResult(BaseModel):
    stage: Stage
    key_header: str
    headers: list[str]
    source_headers: list[str]  # headers of the file, before column rules
    rows: list[PipelineRow]
    hidden_rows: list[PipelineRow] = Field(default_factory=list)  # only at stage "rows" and later
    issues: list[RuleIssue] = Field(default_factory=list)


def _fmt(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return str(value)
        return str(int(value)) if value.is_integer() else f"{value:.10g}"
    return str(value)


def _as_value(text: str) -> object:
    t = text.strip()
    if NUMBER.match(t):
        f = float(t)
        return int(f) if f.is_integer() and "." not in t and "e" not in t.lower() else f
    return text


class _Expr:
    """A recipe expression with <<Column>> references bound as variables, so a cell
    value can never change the meaning of the expression (PRD 11, item 11). It is checked
    against what calculated columns allow (see functions.py) before it can run."""

    def __init__(self, source: str):
        self.source = source
        self.columns: list[str] = []
        self.quoted: set[str] = set()

        def sub(m: re.Match) -> str:
            col = m.group(2)
            if col not in self.columns:
                self.columns.append(col)
            if m.group(1):
                self.quoted.add(col)  # "<<X>>": always text
            return f"_c{self.columns.index(col)}"

        code = REF.sub(sub, source).strip()
        self.problem: str | None = None  # what isn't allowed in it
        self.code = ""
        if code:
            try:
                self.code = prepare(code)
            except (NotAllowed, SyntaxError) as exc:
                self.problem = str(exc.msg if isinstance(exc, SyntaxError) and exc.msg else exc)

    @property
    def text(self) -> bool:
        """Plain text, used as it is: no columns, and not an allowed expression (e.g. Motor)."""
        return self.problem is not None and not self.columns

    def bind(self, ai: Interpreter, values: dict[str, str]) -> None:
        for i, col in enumerate(self.columns):
            raw = values.get(col, "")
            ai.symtable[f"_c{i}"] = raw if col in self.quoted else _as_value(raw)

    def run(self, ai: Interpreter, literal_fallback: bool) -> tuple[object, bool]:
        """Returns (value, ok). With literal_fallback, plain text such as `Motor`
        that isn't an allowed expression is used as the value itself (it is never run)."""
        if literal_fallback and self.text:
            return self.source.strip(), True
        if self.problem:
            return None, False
        if not self.code:
            return "", True
        ai.error = []
        value = ai(self.code, show_errors=False)
        if ai.error:
            return None, False
        return value, True


def _evaluate_auto(rows: list[PipelineRow], headers: list[str], recipe: Recipe,
                   issues: list[RuleIssue]) -> None:
    for col in recipe.auto_columns:
        name = col.name.strip()
        if not name:
            continue
        if name in headers:
            issues.append(RuleIssue(kind="auto", rule=name, message="A column with this name already exists; skipped."))
            continue
        # (condition, NOT it, value): the If, then each Else if, in order; then the Else.
        cases = [(_Expr(col.statement), col.negate, _Expr(col.true_val))]
        cases += [(_Expr(b.statement), b.negate, _Expr(b.value)) for b in col.else_ifs]
        otherwise = _Expr(col.false_val)
        exprs = [e for test, _neg, value in cases for e in (test, value)] + [otherwise]
        missing = sorted({c for e in exprs for c in e.columns if c not in headers})
        # What isn't allowed: in a condition always; in a value only when it refers to a column (else it is plain text).
        labels = [("If", cases[0][0]), ("Then", cases[0][2])]
        labels += [(f"Else if {n}{part}", e) for n, (test, _neg, value) in enumerate(cases[1:], start=1)
                   for part, e in ((" condition", test), (" then", value))]
        labels += [("Else", otherwise)]
        bad = [f"{where}: {e.problem}" for where, e in labels if e.problem and (e in [c[0] for c in cases] or e.columns)]
        if bad:
            issues.append(RuleIssue(kind="auto", rule=name, message="Not allowed, so every row gets the error value. "
                                    + "; ".join(bad)))
            missing = missing or ["(not allowed)"]
        if missing and not bad:
            issues.append(RuleIssue(kind="auto", rule=name,
                                    message=f"Refers to missing column(s): {', '.join(missing)}; every row gets the error value."))
        ai = make_interpreter()
        for row in rows:
            result: object = None
            if not missing:
                # Each expression numbers its own columns (_c0, _c1...), so it is bound just before it runs.
                branch, ok = otherwise, True
                for test, negate, value in cases:
                    test.bind(ai, row.values)
                    held, ok = test.run(ai, literal_fallback=False)
                    if not ok:
                        break
                    if bool(held) != negate:
                        branch = value
                        break
                if ok:
                    branch.bind(ai, row.values)
                    result, ok = branch.run(ai, literal_fallback=True)
                if not ok:
                    result = None
            if result is None:
                row.values[name] = col.error_val
                row.auto_errors.append(name)
            else:
                row.values[name] = _fmt(result)
        headers.append(name)


def run_pipeline(rev: Revision, recipe: Recipe, upto: Stage = "auto") -> PipelineResult:
    stop = STAGES.index(upto)
    key = rev.key_header
    issues: list[RuleIssue] = []
    rows = [PipelineRow(key=r[key], origin="file", file_row=rev.file_rows[i] if i < len(rev.file_rows) else i + 1, values=dict(r))
            for i, r in enumerate(rev.rows)]
    headers = list(rev.headers)
    hidden_rows: list[PipelineRow] = []

    def done() -> PipelineResult:
        # Built at the end: pydantic copies lists, so later edits wouldn't show otherwise.
        return PipelineResult(stage=upto, key_header=key, headers=headers, source_headers=list(rev.headers),
                              rows=rows, hidden_rows=hidden_rows, issues=issues)

    if stop < 1:
        return done()

    # 1. Columns: hide / rename (the key column is always shown and never renamed).
    rules = {c.header: c for c in recipe.columns}
    for h in rules:
        if h not in rev.headers:
            issues.append(RuleIssue(kind="columns", rule=h, message="Column not in the latest file."))
    new_headers: list[str] = []
    renames: dict[str, str] = {}
    for h in headers:
        rule = rules.get(h)
        if h != key and rule and not rule.visible:
            continue
        name = h
        if h != key and rule and rule.rename and rule.rename.strip() and rule.rename.strip() != h:
            wanted = rule.rename.strip()
            if wanted in headers or wanted in renames.values():
                issues.append(RuleIssue(kind="columns", rule=h, message=f"Can't rename to '{wanted}': that name is taken."))
            else:
                name = wanted
                renames[h] = wanted
        new_headers.append(name)
    for row in rows:
        row.values = {renames.get(h, h): row.values[h] for h in headers if renames.get(h, h) in new_headers}
    headers[:] = new_headers
    if stop < 2:
        return done()

    # 2. Rows: hide by key.
    hidden = {r.key for r in recipe.hidden_rows}
    keys = {r.key for r in rows}
    for k in sorted(hidden - keys):
        issues.append(RuleIssue(kind="rows", rule=k, message="Row key not in the latest file."))
    hidden_rows = [r for r in rows if r.key in hidden]
    rows[:] = [r for r in rows if r.key not in hidden]
    if stop < 3:
        return done()

    # 3. Text columns.
    for tc in recipe.text_columns:
        name = tc.name.strip()
        if not name:
            continue
        if name in headers:
            issues.append(RuleIssue(kind="text", rule=name, message="A column with this name already exists; skipped."))
            continue
        headers.append(name)
        for row in rows:
            row.values[name] = tc.value
    if stop < 4:
        return done()

    # 4. Overrides.
    by_key = {r.key: r for r in rows}
    for ov in recipe.overrides:
        row = by_key.get(ov.key)
        if row is None:
            where = "is hidden" if ov.key in hidden and ov.key in keys else "is not in the latest file"
            issues.append(RuleIssue(kind="overrides", rule=f"{ov.key} / {ov.column}", message=f"Row {where}."))
        elif ov.column not in headers:
            issues.append(RuleIssue(kind="overrides", rule=f"{ov.key} / {ov.column}", message="Column not in the table."))
        else:
            row.values[ov.column] = ov.value
            row.overridden.append(ov.column)
    if stop < 5:
        return done()

    # 5. Custom rows (cells default to "-"; the key must not clash with a file row).
    seen = set(keys)
    for cr in recipe.custom_rows:
        k = cr.key.strip()
        if not k or k in seen:
            issues.append(RuleIssue(kind="custom", rule=k or "(blank)",
                                    message="Key is blank or already used by another row; skipped."))
            continue
        seen.add(k)
        extra = sorted(set(cr.values) - set(headers))
        if extra:
            issues.append(RuleIssue(kind="custom", rule=k, message=f"Values for missing column(s) ignored: {', '.join(extra)}"))
        values = {h: cr.values.get(h, "-") for h in headers}
        values[key] = k
        rows.append(PipelineRow(key=k, origin="custom", file_row=None, values=values))
    if stop < 6:
        return done()

    # 6. Find / replace columns.
    for fr in recipe.find_replace:
        name = fr.name.strip()
        if not name:
            continue
        if name in headers:
            issues.append(RuleIssue(kind="replace", rule=name, message="A column with this name already exists; skipped."))
            continue
        if fr.column not in headers:
            issues.append(RuleIssue(kind="replace", rule=name, message=f"Column '{fr.column}' is not in the table; skipped."
                                    if fr.column else "No column chosen; skipped."))
            continue
        table = {r.find: r.replace for r in fr.replacements}
        for row in rows:
            value = row.values.get(fr.column, "")
            row.values[name] = table.get(value, value)
        headers.append(name)
    if stop < 7:
        return done()

    # 7. Calculated columns.
    _evaluate_auto(rows, headers, recipe, issues)
    return done()


class LoadListResult(BaseModel):
    fields: list[str]  # mapped fields, in load-list order
    rows: list[dict[str, str | float | int | bool | None]]
    warnings: list[str] = Field(default_factory=list)


def output_list(result: PipelineResult, recipe: Recipe, load_fields=None) -> LoadListResult:
    """Map the final table onto the target's fields (PRD 5.11 / 5.13): the load list for
    MEL, the instrument list for PIL. `load_fields`: the project's Load List fields
    (load_fields.LoadFields; default the built-in ones), with which are numbers and yes/no."""
    maps = {m.field: m for m in recipe.mapping if m.column or m.manual is not None}
    project = load_fields is not None and recipe.target != "PIL"
    fields = [f for f in fields_for(recipe.target, load_fields.importable() if project else None) if f in maps]
    numeric = load_fields.numeric() if project else TARGET_NUMERIC.get(recipe.target, NUMERIC_FIELDS)
    boolean = load_fields.boolean() if project else TARGET_BOOLEAN.get(recipe.target, {"is_a_loadcentre", "is_deleted"})
    warnings: list[str] = []
    for f in fields:
        m = maps[f]
        if m.column and m.column not in result.headers:
            warnings.append(f"'{f}' is mapped to missing column '{m.column}'.")
    bad: dict[str, int] = {}
    out = []
    for row in result.rows:
        rec: dict[str, str | float | int | bool | None] = {}
        for f in fields:
            m = maps[f]
            raw = m.manual if not m.column else row.values.get(m.column, "")
            raw = "" if raw is None else str(raw).strip()
            value: str | float | int | bool | None = raw
            if f in numeric:
                if raw in ("", "-"):
                    value = None
                elif NUMBER.match(raw):
                    value = _as_value(raw)  # type: ignore[assignment]
                else:
                    bad[f] = bad.get(f, 0) + 1  # kept as text so nothing is lost
            elif f in boolean:
                value = raw.lower() in ("true", "yes", "y", "1", "x")
            rec[f] = value
        out.append(rec)
    for f, n in bad.items():
        warnings.append(f"{n} row(s) have a non-numeric '{f}'; kept as text.")
    return LoadListResult(fields=fields, rows=out, warnings=warnings)


load_list = output_list  # the original name, for MEL callers
