# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""The Load List Summary Page: tables that total up the Load List.

A page has any number of tables. A table:

- **filter**: which loads it looks at: the active loads for which the condition holds (blank:
  all of them), e.g. `<<Strike through>> != 'Full Row' and <<loadtype>> != 'SPARE'`.
- **rows**, each typed in: a name, a condition choosing its loads among the filtered ones
  (`'TX-1' in <<supplychain>>`: everything fed from TX-1, directly or through MCCs below it),
  and optionally a **reference load** by tag whose own values its formulas can use as
  `<<Ref.field>>` (the transformer's rating, for its % loading).
- **columns**, in order:
  - an **aggregate**: Sum, Count, Min, Max or Average of a load field (any Load List field,
    calculated ones too, or what the app works out: rating, voltage, cable length…), over the
    row's loads for which the column's own condition holds (blank: all). Count counts loads.
    Blanks and text are left out of the others.
  - a **formula**: like a Load List calculated field, over the row's other columns
    (`<<Total kVA>>`, by name), `<<Ref.field>>`, `<<Row>>` (the row's name) and `<<Loads>>`
    (how many loads the row has): Applies when, Formula, Otherwise, Decimals and checks.
- an optional **total row**, over every load the table's filter lets in.

Expressions are those of the Load List's calculated fields (keylists.load_calcs, mel.functions):
a load's cells by <<name>> (load_cells), the same functions and operators.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from ..mel.functions import make_interpreter
from ..mel.load_fields import CalcCheck
from ..refdata.models import RefValidationError, new_id
from ..refdata.validate import name_key
from .load_calcs import VALUE, _Expr, _round, load_cells, refs
from .loadlist import LoadListRow
from .models import LoadType

Func = Literal["sum", "count", "min", "max", "average"]
FUNCS: dict[str, str] = {"sum": "Sum", "count": "Count", "min": "Min", "max": "Max", "average": "Average"}
REF = "ref"
ROW_NAME, LOADS = "row", "loads"
TOTAL = "Total"


def norm(name: str) -> str:
    return re.sub(r"[\s_]+", "", name).casefold()


class SummaryColumn(BaseModel):
    id: str = Field(default_factory=new_id)
    name: str  # what it is called, and what formulas call it: <<Total kW>>
    kind: Literal["aggregate", "formula"] = "aggregate"
    # an aggregate
    func: Func = "sum"
    field: str = "load_rating"  # a load cell: a Load List field's key or an app tag
    condition: str = ""  # which of the row's loads it takes (blank: all)
    # a formula (and the rounding of an aggregate)
    applies_if: str = ""
    formula: str = ""
    otherwise: str = ""
    decimals: int | None = Field(default=None, ge=0, le=10)
    checks: list[CalcCheck] = Field(default_factory=list)


class SummaryRow(BaseModel):
    id: str = Field(default_factory=new_id)
    name: str
    condition: str = ""  # which of the table's loads it takes (blank: all)
    ref_tag: str = ""  # a load whose own values its formulas can use as <<Ref.field>>


class SummaryTable(BaseModel):
    id: str = Field(default_factory=new_id)
    name: str
    filter: str = ""  # which active loads the table looks at (blank: all)
    columns: list[SummaryColumn] = Field(default_factory=list)
    rows: list[SummaryRow] = Field(default_factory=list)
    total_row: bool = True


class SummaryPage(BaseModel):
    tables: list[SummaryTable] = Field(default_factory=list)


# -- what a page works out to --------------------------------------------------------------------

class SummaryIssue(BaseModel):
    column: str = ""  # a column's id ("" for the row as a whole)
    severity: Literal["error", "warning"]
    message: str


class SummaryOutRow(BaseModel):
    name: str
    total: bool = False
    loads: int  # how many loads it has
    tags: list[str]  # their tags (for "which loads?")
    cells: list[str | int | float | bool | None]  # by column
    issues: list[SummaryIssue] = Field(default_factory=list)


class SummaryOutTable(BaseModel):
    id: str
    name: str
    columns: list[str]
    rows: list[SummaryOutRow]
    issues: list[str] = Field(default_factory=list)  # the table's filter or a row's condition can't be worked out…


def _number(v: object) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip())
    except ValueError:
        return None


def _key(name: str) -> str:
    """How a name is matched: ignoring case, spaces and _ (Ref.Load Rating = ref.load_rating)."""
    n = name.strip().casefold()
    return f"{REF}.{norm(n[len(REF) + 1:])}" if n.startswith(f"{REF}.") else norm(n)


def _ex(text: str) -> _Expr:
    """An expression whose <<names>> are matched by _key."""
    e = _Expr.of(text)
    e.names = [_key(n) for n in e.names]
    return e


def _aggregate(func: str, values: list[object]) -> object:
    if func == "count":
        return len(values)
    nums = [n for n in (_number(v) for v in values) if n is not None]
    if not nums:
        return ""
    out = {"sum": sum(nums), "min": min(nums), "max": max(nums), "average": sum(nums) / len(nums)}[func]
    return int(out) if float(out).is_integer() else out


def _formula_order(t: SummaryTable) -> list[SummaryColumn]:
    """The formula columns in an order each can be worked out after the ones it uses. Raises
    ValueError naming those in a loop."""
    formulas = {norm(c.name): c for c in t.columns if c.kind == "formula"}
    uses = {k: {_key(r) for r in refs(" ".join([c.applies_if, c.formula, c.otherwise]))} & set(formulas) - {k}
            for k, c in formulas.items()}
    done: list[str] = []
    while len(done) < len(formulas):
        ready = [k for k in formulas if k not in done and uses[k] <= set(done)]
        if not ready:
            raise ValueError(", ".join(formulas[k].name for k in formulas if k not in done))
        done += ready
    return [formulas[k] for k in done]


def check_page(page: SummaryPage, load_names: set[str]) -> SummaryPage:
    """Tidy and check a page: names required and unique (tables in the page, rows and columns in
    their table, ignoring case, spaces and _); column names not Row, Loads or Ref; every
    expression allowed (mel.functions), referring to load cells (`load_names`, lower case) in a
    filter, condition or aggregate, and to the table's columns, <<Row>>, <<Loads>> and
    <<Ref.field>> in a formula; formulas not in a loop. Raises RefValidationError with fields
    `<t>.name`, `<t>.filter`, `<t>.rows.<r>.<part>`, `<t>.columns.<c>.<part>`."""
    errors: dict[str, str] = {}
    tables: list[SummaryTable] = []
    seen_t: set[str] = set()

    load_norm = {norm(n) for n in load_names}

    def expr(where: str, label: str, text: str, allowed: set[str], loads: bool = False) -> None:
        e = _ex(text)
        bad = [n for n in e.names if n not in allowed and not (loads and n in load_norm)
               and not (n.startswith(f"{REF}.") and REF in allowed)]
        if bad:
            errors[where] = f"{label}: not something it can use: " + ", ".join(f"<<{n}>>" for n in bad)
        elif e.problem:
            errors[where] = f"{label}: {e.problem}"

    for ti, t in enumerate(page.tables):
        t = t.model_copy(deep=True)
        t.name = " ".join(t.name.split())
        if not t.name:
            errors[f"{ti}.name"] = "A table needs a name"
        elif name_key(t.name) in seen_t:
            errors[f"{ti}.name"] = f"Two tables are called {t.name}"
        seen_t.add(name_key(t.name))
        expr(f"{ti}.filter", "Filter", t.filter, set(), loads=True)
        seen: set[str] = set()
        for ci, c in enumerate(t.columns):
            c.name = " ".join(c.name.split())
            where = f"{ti}.columns.{ci}"
            if not c.name:
                errors[f"{where}.name"] = "A column needs a name"
            elif norm(c.name) in (ROW_NAME, LOADS, REF):
                errors[f"{where}.name"] = f"'{c.name}' is taken: <<Row>>, <<Loads>> and <<Ref.…>> are the row's own"
            elif norm(c.name) in seen:
                errors[f"{where}.name"] = f"Two columns are called {c.name}"
            seen.add(norm(c.name))
            if c.kind == "aggregate":
                if c.func != "count" and norm(c.field) not in {norm(n) for n in load_names}:
                    errors[f"{where}.field"] = f"'{c.field}' is not a field of the Load List"
                expr(f"{where}.condition", "Condition", c.condition, set(), loads=True)
            elif not c.formula.strip():
                errors[f"{where}.formula"] = "A formula column needs a formula"
            c.checks = [ch for ch in c.checks if ch.rule.strip()]
        names = {norm(c.name) for c in t.columns} | {ROW_NAME, LOADS, REF}
        for ci, c in enumerate(t.columns):
            where = f"{ti}.columns.{ci}"
            if c.kind == "formula":
                for part, label in (("applies_if", "Applies when"), ("formula", "Formula"), ("otherwise", "Otherwise")):
                    expr(f"{where}.{part}", label, getattr(c, part), names)
                    if norm(c.name) in {_key(r) for r in refs(getattr(c, part))}:
                        errors[f"{where}.{part}"] = f"{label}: it can't use its own answer; in a check, use <<value>>"
            for n, ch in enumerate(c.checks):
                expr(f"{where}.checks.{n}", f"Check {n + 1}", ch.rule, names | {VALUE})
        try:
            _formula_order(t)
        except ValueError as exc:
            errors[f"{ti}.columns"] = f"These formula columns use each other in a loop: {exc}"
        seen_r: set[str] = set()
        for ri, r in enumerate(t.rows):
            r.name = " ".join(r.name.split())
            r.ref_tag = r.ref_tag.strip()
            where = f"{ti}.rows.{ri}"
            if not r.name:
                errors[f"{where}.name"] = "A row needs a name"
            elif name_key(r.name) in seen_r or name_key(r.name) == name_key(TOTAL) and t.total_row:
                errors[f"{where}.name"] = f"Two rows are called {r.name}"
            seen_r.add(name_key(r.name))
            expr(f"{where}.condition", "Condition", r.condition, set(), loads=True)
        tables.append(t)
    if errors:
        raise RefValidationError(f"{len(errors)} problem(s) in the summary page.", errors)
    return SummaryPage(tables=tables)


def work_out(page: SummaryPage, loads: list[LoadListRow], load_types: dict[str, LoadType],
             areas: dict[str, tuple[str, str]], motors: list | None = None, drives: list | None = None,
             starters=None) -> list[SummaryOutTable]:
    """Every table of the page over the Load List as it is (`loads`: its rows, with their
    calculated fields worked out)."""
    by_ref = {r.ref(): r for r in loads}
    active = [r for r in loads if r.status == "active"]
    cells = {r.ref(): {norm(k): v for k, v in load_cells(r, load_types, areas, by_ref, motors, drives, starters).items()} for r in active}
    by_tag = {name_key(r.tag()): r for r in active}
    ai = make_interpreter()
    out = []
    for t in page.tables:
        issues: list[str] = []
        flt = _ex(t.filter)
        chosen = []
        bad = 0
        for r in active:
            ok, why = flt.run(ai, cells[r.ref()]) if flt.code or flt.problem else (True, None)
            if why:
                bad += 1
            elif ok:
                chosen.append(r)
        if bad:
            issues.append(f"The filter can't be worked out for {bad} load(s): they are left out")
        try:
            formulas = _formula_order(t)
        except ValueError:
            formulas = [c for c in t.columns if c.kind == "formula"]
        conds = {c.id: _ex(c.condition) for c in t.columns if c.kind == "aggregate"}
        parts = {c.id: (_ex(c.applies_if), _ex(c.formula), _ex(c.otherwise), [(_ex(ch.rule), ch) for ch in c.checks])
                 for c in formulas}

        def one(name: str, members: list[LoadListRow], ref: LoadListRow | None, total: bool) -> SummaryOutRow:
            values: dict[str, object] = {}
            row_issues: list[SummaryIssue] = []
            for c in t.columns:
                if c.kind != "aggregate":
                    continue
                take, wrong = [], 0
                for m in members:
                    e = conds[c.id]
                    ok, why = e.run(ai, cells[m.ref()]) if e.code or e.problem else (True, None)
                    wrong += bool(why)
                    if ok and not why:
                        take.append(cells[m.ref()].get(norm(c.field), ""))
                if wrong:
                    row_issues.append(SummaryIssue(column=c.id, severity="warning",
                                                   message=f"The condition can't be worked out for {wrong} load(s): left out"))
                values[c.id] = _round(_aggregate(c.func, take), c.decimals)
            names: dict[str, object] = {ROW_NAME: name, LOADS: len(members)}
            for c in t.columns:
                if c.id in values:
                    names[norm(c.name)] = values[c.id]
            if ref is not None:
                names |= {f"{REF}.{k}": v for k, v in cells[ref.ref()].items()}  # already matched by norm
            for c in formulas:
                test, formula, otherwise, checks = parts[c.id]
                applies, why = (True, None) if not test.code and not test.problem else test.run(ai, names)
                if why:
                    answer: object = ""
                    row_issues.append(SummaryIssue(column=c.id, severity="error", message=f"Applies when can't be worked out: {why}"))
                elif not applies:
                    answer, why = otherwise.run(ai, names)
                    if why:
                        row_issues.append(SummaryIssue(column=c.id, severity="error", message=f"Otherwise can't be worked out: {why}"))
                        answer = ""
                else:
                    answer, why = formula.run(ai, names)
                    if why:
                        row_issues.append(SummaryIssue(column=c.id, severity="error", message=f"Can't be worked out: {why}"))
                        answer = ""
                answer = _round(answer, c.decimals)
                if isinstance(answer, float) and answer != answer:
                    answer = ""
                values[c.id] = answer if isinstance(answer, (str, int, float, bool)) or answer is None else str(answer)
                names[norm(c.name)] = answer
            for c in t.columns:  # checks, on every column's answer
                for rule, ch in [(_ex(ch.rule), ch) for ch in c.checks]:
                    if values.get(c.id) in ("", None):
                        continue
                    ok, why = rule.run(ai, names | {VALUE: values[c.id]})
                    if why:
                        row_issues.append(SummaryIssue(column=c.id, severity="warning", message=f"Check {ch.rule} can't be worked out: {why}"))
                    elif not ok:
                        row_issues.append(SummaryIssue(column=c.id, severity=ch.severity, message=ch.message.strip() or f"Fails the check {ch.rule}"))
            return SummaryOutRow(name=name, total=total, loads=len(members), tags=[m.tag() for m in members],
                                 cells=[values.get(c.id, "") for c in t.columns], issues=row_issues)

        rows = []
        for r in t.rows:
            cond = _ex(r.condition)
            members, wrong = [], 0
            for m in chosen:
                ok, why = cond.run(ai, cells[m.ref()]) if cond.code or cond.problem else (True, None)
                wrong += bool(why)
                if ok and not why:
                    members.append(m)
            ref = by_tag.get(name_key(r.ref_tag)) if r.ref_tag else None
            row = one(r.name, members, ref, False)
            if wrong:
                row.issues.append(SummaryIssue(severity="warning", message=f"The row's condition can't be worked out for {wrong} load(s): left out"))
            if r.ref_tag and ref is None:
                row.issues.append(SummaryIssue(severity="error", message=f"No active load is tagged {r.ref_tag}: <<Ref.…>> is blank"))
            rows.append(row)
        if t.total_row:
            rows.append(one(TOTAL, chosen, None, True))
        out.append(SummaryOutTable(id=t.id, name=t.name, columns=[c.name for c in t.columns], rows=rows, issues=issues))
    return out


__all__ = ["FUNCS", "SummaryColumn", "SummaryRow", "SummaryTable", "SummaryPage", "SummaryOutTable", "check_page", "work_out"]
