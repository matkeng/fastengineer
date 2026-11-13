# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Calculated fields of the Project Master Load List: worked out for each row, like a
spreadsheet formula that refers to the row's other cells.

A calculated field (mel.load_fields.LoadCalc) has:

- **Applies when**: a condition for the rows it is relevant to (blank: every row). Other rows
  get **Otherwise** (blank: nothing) and are not checked.
- **Formula**: one expression, giving the answer. It refers to the row's cells as <<field>>:
  any Load List field by its key (an import's value as it is, a number staying a number), a
  calculated field (worked out first, in the order they depend on each other), the load's
  cable (<<cable_length>>, <<cable_size>>…) and what the app works out for the row
  (<<loadtype>>, <<voltage>>, <<plantarea>>…, the same tags load types' rows use).
- **Decimals**: a number answer is rounded to this many places.
- **Checks**: expressions that hold for a good answer, with <<value>> the answer: an error or a
  warning with a message when one doesn't hold.

Expressions allow exactly what List import's calculated columns allow (mel.functions): the
same functions, operators and `A if condition else B`. A blank cell is "", so a formula that
must treat it as zero writes `(<<field>> or 0)`.

A formula that can't be worked out for a row (a blank or text where a number is needed,
division by zero…) leaves the cell blank with an error saying why.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pydantic import BaseModel

from ..mel.functions import NotAllowed, make_interpreter, prepare
from ..mel.load_fields import LoadCalc, LoadFields
from ..refdata.models import RefValidationError
from .loadgen import _NUMBER, tags_for
from .loadlist import CABLE_FIELDS, LoadListRow
from .models import LoadType

REF = re.compile(r"""(["']?)<<\s*(.+?)\s*>>\1""")
VALUE = "value"  # in a check: the answer
#: What the app works out for a row that a formula can use (loadgen.tags_for), with what each is.
APP_REFS: list[tuple[str, str]] = [
    ("description", "the description"), ("rating", "the load rating"),
    ("units", "the rating's units (the import's, else the load type's)"),
    ("voltage", "the voltage (the import's, else the load type's)"), ("phases", "the phases (the import's, else the load type's)"),
    ("qty", "the quantity"), ("equiptype", "the equipment type"), ("plantarea", "the plant area's tag"),
    ("plantareadesc", "the plant area's description"), ("loadtype", "the load type's code"), ("loadtypename", "the load type's name"),
    ("suppliedfrom", "the tag of the panel it is supplied from"), ("suppliedfromdesc", "that panel's description"),
    ("stddrg", "the load type's STD drawing"), ("buckettype", "the load type's bucket type"), ("source", "the import it comes from"),
    ("cable_length", "the power cable's length (m)"), ("cable_construction", "Multicore or Single core"),
    ("cable_parallel", "cables in parallel"), ("cable_insulation", "the cable insulation"), ("cable_size", "the cable size (mm²)"),
    ("earth_size", "the earth cable size (mm²)"),
    ("ispanel", "True when it is a distribution panel (MCC, switchboard…)"),
    ("supplychain", "the panels it is fed from, nearest first: 'TX-1' in <<supplychain>> is true for every load fed from TX-1, "
                    "directly or through panels below it"),
]


class CalcIssue(BaseModel):
    field: str  # the calculated field's key
    severity: str  # "error" or "warning"
    message: str


def refs(text: str) -> list[str]:
    """The fields an expression refers to (lower case, in order, once each)."""
    return list(dict.fromkeys(m.group(2).casefold() for m in REF.finditer(text or "")))


@dataclass
class _Expr:
    source: str
    names: list[str] = field(default_factory=list)
    code: str = ""
    problem: str | None = None

    @classmethod
    def of(cls, source: str) -> _Expr:
        e = cls(source=source or "")
        names: list[str] = []

        def sub(m: re.Match) -> str:
            n = m.group(2).casefold()
            if n not in names:
                names.append(n)
            return f"_c{names.index(n)}"

        code = REF.sub(sub, e.source).strip()
        e.names = names
        if code:
            try:
                e.code = prepare(code)
            except (NotAllowed, SyntaxError) as exc:
                e.problem = str(exc.msg if isinstance(exc, SyntaxError) and exc.msg else exc)
        return e

    def run(self, ai, cells: dict[str, object]) -> tuple[object, str | None]:
        """(value, why it couldn't be worked out)."""
        if self.problem:
            return None, self.problem
        if not self.code:
            return "", None
        for i, n in enumerate(self.names):
            ai.symtable[f"_c{i}"] = cells.get(n, "")
        ai.error = []
        value = ai(self.code, show_errors=False)
        if ai.error:
            kind, msg = ai.error[0].get_error()
            return None, _plain(kind, msg)
        return value, None


def _plain(kind: str, msg: str) -> str:
    """An evaluator error in words."""
    msg = re.sub(r"\b_c\d+\b", "a cell", str(msg)).strip().splitlines()[-1] if msg else ""
    if kind == "ZeroDivisionError":
        return "division by zero"
    if kind == "TypeError" and ("str" in msg or "NoneType" in msg):
        return "a cell is blank or text where a number is needed"
    return f"{kind}: {msg}" if msg else kind


def _value(x: object) -> object:
    if isinstance(x, str):
        t = x.strip()
        if _NUMBER.match(t):
            f = float(t)
            return int(f) if f.is_integer() and "." not in t else f
    return x


def _motor_refs() -> list[tuple[str, str]]:
    from .motors import NUMBERS, TEXTS

    out = [("motor.partno", "the matched motor's part number (Motor Data, by the load's rating and Poles)")]
    out += [(f"motor.{t.replace(' ', '').replace('/', '').casefold()}", f"the matched motor's {m}")
            for f, (t, m) in {**TEXTS, **NUMBERS}.items() if f != "part_no"]
    return out


def _drive_refs() -> list[tuple[str, str]]:
    from .drives import NUMBERS, TEXTS

    out = [("drive.catno", "the matched drive's catalog number (Drive Data, by voltage, Drive enclosure, Drive duty and the motor's FLC)"),
           ("drive.amps", "the matched drive's continuous output amps at the load's duty"),
           ("drive.amps1min", "its 1 min output amps at the load's duty"), ("drive.amps3s", "its 3 s output amps at the load's duty"),
           ("drive.kw", "its power (kW) at the load's duty"), ("drive.hp", "its power (Hp) at the load's duty"),
           ("drive.duty", "the duty it was matched on: ND or HD"), ("drive.voltagerange", "its voltage range")]
    out += [(f"drive.{t.replace(' ', '').casefold()}", f"the matched drive's {m}") for f, (t, m) in {**TEXTS, **NUMBERS}.items()
            if f != "cat_no"]
    return out


def _starter_refs() -> list[tuple[str, str]]:
    from .starters import NUMBERS, TEXTS

    out = [("starter.cb", "the load's Type 2 starter circuit breaker (Starter Coordination: its load type's chart, by its rating)"),
           ("starter.range", "its overload setting range, e.g. 5.4 – 27"), ("starter.description", "what its chart is"),
           ("starter.notetext", "what its chart note says")]
    out += [(f"starter.{t.replace(' ', '').casefold()}", f"the load's starter's {m}") for f, (t, m) in {**TEXTS, **NUMBERS}.items()
            if f != "cb"]
    return out


#: What a calculation can use about a load's matched motor (keylists.motors), drive and starter:
#: <<Motor.FLC>>, <<Drive.CatNo>>, <<Starter.CB>>…
def _load_factor_refs() -> list[tuple[str, str]]:
    from .load_factors import NUMBERS, TEXTS

    out = [(f"loadfactor.{t.replace(' ', '').casefold()}", f"the load's {m} (Load Factors, by its Equipment type; else the Default row)")
           for f, (t, m) in {**NUMBERS, **TEXTS}.items()]
    return out + [("loadfactor.matched", "True when the load's equipment type has its own Load Factors row, False for the Default row")]


MOTOR_REFS: list[tuple[str, str]] = _motor_refs() + _drive_refs() + _starter_refs() + _load_factor_refs()


def known_refs(fields: LoadFields) -> set[str]:
    return {f.key.casefold() for f in fields.fields} | {r for r, _ in APP_REFS} | {r for r, _ in MOTOR_REFS} | {"tag"}


def order(fields: LoadFields) -> list[str]:
    """The calculated fields' keys in the order they can be worked out (each after the ones it
    uses). Raises ValueError naming the fields in a loop."""
    calcs = {f.key: f.calc for f in fields.calcs()}
    uses = {k: {r for r in _calc_refs(c) if r in calcs and r != k} for k, c in calcs.items()}
    done: list[str] = []
    while len(done) < len(calcs):
        ready = [k for k in calcs if k not in done and uses[k] <= set(done)]
        if not ready:
            raise ValueError(", ".join(k for k in calcs if k not in done))
        done += ready
    return done


def _calc_refs(c: LoadCalc) -> list[str]:
    return refs(" ".join([c.applies_if, c.formula, c.otherwise]))


def check_calcs(fields: LoadFields) -> None:
    """The calculated fields' expressions: allowed (see mel.functions), referring only to fields
    and what the app works out, and not in a loop. Raises RefValidationError with the field's
    position: `<i>.applies_if`, `<i>.formula`, `<i>.otherwise`, `<i>.checks.<n>` or `<i>`."""
    errors: dict[str, str] = {}
    known = known_refs(fields)
    labels = {f.key.casefold(): f.label for f in fields.fields}
    for i, f in enumerate(fields.fields):
        if f.kind != "calc" or f.calc is None:
            continue
        c = f.calc
        parts = [("applies_if", c.applies_if, "Applies when"), ("formula", c.formula, "Formula"), ("otherwise", c.otherwise, "Otherwise")]
        parts += [(f"checks.{n}", ch.rule, f"Check {n + 1}") for n, ch in enumerate(c.checks)]
        for where, text, name in parts:
            e = _Expr.of(text)
            unknown = [r for r in e.names if r not in known and not (where.startswith("checks") and r == VALUE)]
            if unknown:
                errors[f"{i}.{where}"] = f"{name}: not a field of the Load List: " + ", ".join(f"<<{r}>>" for r in unknown)
            elif e.problem:
                errors[f"{i}.{where}"] = f"{name}: {e.problem}"
            elif f.key.casefold() in e.names:
                errors[f"{i}.{where}"] = f"{name}: it can't use its own answer (<<{f.key}>>); in a check, use <<value>>"
    try:
        order(fields)
    except ValueError as exc:
        loop = [labels.get(k, k) for k in str(exc).split(", ")]
        errors["fields"] = f"These calculated fields use each other in a loop: {', '.join(loop)}"
    if errors:
        raise RefValidationError(f"{len(errors)} problem(s) in the calculated fields.", errors)


def _round(x: object, decimals: int | None) -> object:
    if decimals is None or isinstance(x, bool) or not isinstance(x, (int, float)):
        return x
    r = round(float(x), decimals)
    return int(r) if decimals == 0 else r


def supply_chain(row: LoadListRow, by_ref: dict[str, LoadListRow]) -> list[str]:
    """The tags of the panels a load is fed from, nearest first, up to the top (a loop stops it):
    ['MCC-1', 'TX-1', 'MSB-1']. A load fed from Primary Supply ends with 'Primary Supply'."""
    from .loadlist import PRIMARY_SUPPLY

    out: list[str] = []
    seen = {row.ref()}
    ref = row.supplied_from
    while ref and len(out) < 50:
        if ref == PRIMARY_SUPPLY:
            out.append("Primary Supply")
            break
        up = by_ref.get(ref)
        if up is None or up.ref() in seen:
            break
        seen.add(up.ref())
        out.append(up.tag())
        ref = up.supplied_from
    return out


def load_cells(row: LoadListRow, load_types: dict[str, LoadType], areas: dict[str, tuple[str, str]],
               by_ref: dict[str, LoadListRow], motors: list | None = None, drives: list | None = None,
               starters=None, load_factors: list | None = None) -> dict[str, object]:
    """What an expression about a load can refer to, by lower-case name: the app's tags for it,
    its own values (a number staying a number; a blank one leaves what the app works out), its
    cable, <<supplychain>>: the panels it is fed from, nearest first (see supply_chain), and
    <<Motor.…>>: the Motor Data row its rating and poles match (keylists.motors; blank if none)."""
    cells: dict[str, object] = {k: _value(v) for k, v in tags_for(row, load_types, areas, by_ref).items()}
    cells |= {k.casefold(): v for k, v in row.values.items() if v is not None and v != ""}
    cells |= {k.casefold(): "" for k, v in row.values.items() if k.casefold() not in cells}
    cells |= {c: ("" if getattr(row, c) is None else _value(getattr(row, c))) for c in CABLE_FIELDS}
    cells["supplychain"] = supply_chain(row, by_ref)
    cells["ispanel"] = row.is_panel
    from .motors import motor_fields, motor_for
    m = motor_for(cells.get("rating"), cells.get("units"), cells.get("poles"), motors or [])
    cells |= {f"motor.{k}": v for k, v in motor_fields(m).items()}
    from .drives import drive_fields, drive_for_load
    x = drive_for_load(cells.get("rating"), cells.get("units"), cells.get("voltage"), m.flc if m else None,
                       cells.get("drive_duty"), cells.get("drive_enclosure"), drives or [])
    cells |= {f"drive.{k}": v for k, v in drive_fields(x, cells.get("drive_duty")).items()}
    from .starters import starter_fields, starter_for_load
    lt = load_types.get(row.load_type_id or "")
    s = starter_for_load(cells.get("rating"), cells.get("units"), lt.starter_chart if lt else "", starters)
    cells |= {f"starter.{k}": v for k, v in starter_fields(s).items()}
    from .load_factors import load_factor_fields, load_factor_for
    lf, matched = load_factor_for(cells.get("equiptype"), load_factors or [])
    cells |= {f"loadfactor.{k}": v for k, v in load_factor_fields(lf, matched).items()}
    return cells


def apply_calcs(rows: list[LoadListRow], fields: LoadFields, load_types: dict[str, LoadType],
                areas: dict[str, tuple[str, str]], only: str | None = None, motors: list | None = None,
                drives: list | None = None, starters=None, load_factors: list | None = None) -> None:
    """Work out the calculated fields for every row, in place: each answer goes in the row's
    values under the field's key (blank when it can't be worked out), and what is wrong goes in
    its calc_issues. `only`: a calculated field's key, to work out just that one (with what it uses)."""
    calcs = {f.key: f.calc for f in fields.calcs()}
    if not calcs:
        return
    try:
        keys = order(fields)
    except ValueError:
        keys = []  # refused when saved; nothing to work out
    if only is not None and only in calcs:
        need, todo = {only}, [only]
        while todo:
            for r in _calc_refs(calcs[todo.pop()]):
                if r in calcs and r not in need:
                    need.add(r)
                    todo.append(r)
        keys = [k for k in keys if k in need]
    compiled = {k: (_Expr.of(calcs[k].applies_if), _Expr.of(calcs[k].formula), _Expr.of(calcs[k].otherwise),
                    [(_Expr.of(ch.rule), ch) for ch in calcs[k].checks]) for k in keys}
    by_ref = {r.ref(): r for r in rows}
    ai = make_interpreter()
    for row in rows:
        cells = load_cells(row, load_types, areas, by_ref, motors, drives, starters, load_factors)
        issues: list[CalcIssue] = []
        for k in keys:
            test, formula, otherwise, checks = compiled[k]
            applies, why = (True, None) if not test.code and not test.problem else test.run(ai, cells)
            if why:
                issues.append(CalcIssue(field=k, severity="error", message=f"Applies when can't be worked out: {why}"))
                answer: object = ""
            elif not applies:
                answer, why = otherwise.run(ai, cells)
                if why:
                    issues.append(CalcIssue(field=k, severity="error", message=f"Otherwise can't be worked out: {why}"))
                    answer = ""
                answer = _round(answer, calcs[k].decimals)
            else:
                answer, why = formula.run(ai, cells)
                if why:
                    issues.append(CalcIssue(field=k, severity="error", message=f"Can't be worked out: {why}"))
                    answer = ""
                else:
                    answer = _round(answer, calcs[k].decimals)
                    cells[k.casefold()] = answer
                    for rule, ch in checks:
                        ok, why = rule.run(ai, cells | {VALUE: answer})
                        if why:
                            issues.append(CalcIssue(field=k, severity="warning", message=f"Check {ch.rule} can't be worked out: {why}"))
                        elif not ok:
                            issues.append(CalcIssue(field=k, severity=ch.severity, message=ch.message.strip() or f"Fails the check {ch.rule}"))
            if isinstance(answer, float) and answer != answer:  # NaN
                answer = ""
            if answer is None:
                answer = ""
            cells[k.casefold()] = answer
            row.values[k] = answer if isinstance(answer, (str, int, float, bool)) else str(answer)
        row.calc_issues = [i.model_dump() for i in issues]


__all__ = ["APP_REFS", "CalcIssue", "apply_calcs", "check_calcs", "known_refs", "order", "refs"]
