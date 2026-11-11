# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""What a calculated column's expressions can use, checked strictly, and the help the List import
page shows.

An expression is a single Python-like expression (never a statement) and may contain only:

- the columns of the row (<<Column>>), numbers, text in quotes, True, False, None, pi and e;
- the operators + - * / // % **, comparisons (== != < <= > >= in, not in), and, or, not, and
  `A if condition else B`;
- the functions in FUNCTIONS, and the text functions in METHODS written after a text value;
- positions and ranges of text or of a split ([0], [-1], [0:3]) and lists of values ((…), […]).

Anything else (another name, a keyword argument, a lambda, a loop, an assignment, an import,
an attribute that isn't one of METHODS, a name starting with _) refuses the expression, with a
message saying what isn't allowed. check_expression() does that check; prepare() also rewrites
the expression so that % on text and the text functions go through guards that keep the size
of what they build bounded, and make_interpreter() offers nothing but FUNCTIONS and those guards.
The evaluator (asteval) also caps ** and the repetition of text.

FUNCTION_HELP is what the page lists. Every example in it is run by the tests against SAMPLE_ROW,
so the result shown next to it is what the app really gives, and every allowed function appears
in it.
"""

from __future__ import annotations

import ast
import math
import re

from asteval import Interpreter

#: The functions an expression can call: name -> what it is.
FUNCTIONS = {
    "round": round, "abs": abs, "min": min, "max": max, "int": int, "float": float, "str": str, "len": len,
    "ceil": math.ceil, "floor": math.floor, "trunc": math.trunc, "sqrt": math.sqrt, "log": math.log, "log10": math.log10,
    "exp": math.exp, "sin": math.sin, "cos": math.cos, "tan": math.tan, "radians": math.radians, "degrees": math.degrees,
}
#: Text functions, written after a text value: <<Tag>>.upper().
METHODS = ("strip", "lstrip", "rstrip", "upper", "lower", "title", "capitalize", "replace", "startswith", "endswith",
           "split", "find", "count", "zfill", "rjust", "ljust", "isdigit", "isalpha")
#: Names an expression can use besides the columns and the functions.
NAMES = {"True": True, "False": False, "None": None, "pi": math.pi, "e": math.e}
#: The longest expression accepted, the longest text in quotes, and the widest padding or % format.
MAX_EXPRESSION = 1000
MAX_TEXT = 500
MAX_WIDTH = 1000
MAX_RESULT = 100_000  # characters of text a function may build
#: Kept for the tests and the README: what used to be offered and is not.
REMOVED = ("open", "print", "dir")

_COLUMN = re.compile(r"^_c\d+$")
_OPERATORS = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/", ast.FloorDiv: "//", ast.Mod: "%", ast.Pow: "**"}
_COMPARE = (ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn)
_PAD = ("zfill", "rjust", "ljust")
_SPEC = re.compile(r"%(?:\([^)]*\))?[-#0 +]*(\*|\d+)?(?:\.(\*|\d+))?[hlL]?[a-zA-Z%]")


class NotAllowed(ValueError):
    """An expression uses something that isn't allowed; the message says what."""


def _check(node: ast.AST) -> None:
    def no(what: str) -> None:
        raise NotAllowed(what)

    if isinstance(node, ast.Expression):
        return _check(node.body)
    if isinstance(node, ast.Constant):
        if not isinstance(node.value, (str, int, float, bool, type(None))) or isinstance(node.value, complex):
            no(f"{node.value!r} is not allowed")
        if isinstance(node.value, str) and len(node.value) > MAX_TEXT:
            no(f"text in quotes is at most {MAX_TEXT} characters")
        return None
    if isinstance(node, ast.Name):
        if node.id in NAMES or _COLUMN.match(node.id):
            return None
        if node.id in FUNCTIONS:
            no(f"{node.id} is a function: write it with brackets, e.g. {node.id}(…)")
        no(f"'{node.id}' is not allowed: refer to a column as <<Column name>>, and put text in quotes")
    if isinstance(node, ast.BinOp):
        if type(node.op) not in _OPERATORS:
            no("that operator is not allowed: use + - * / // % **")
        _check(node.left)
        return _check(node.right)
    if isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, (ast.UAdd, ast.USub, ast.Not)):
            no("that operator is not allowed")
        return _check(node.operand)
    if isinstance(node, ast.BoolOp):
        for v in node.values:
            _check(v)
        return None
    if isinstance(node, ast.Compare):
        if not all(isinstance(op, _COMPARE) for op in node.ops):
            no("that comparison is not allowed: use == != < <= > >= in, not in")
        for v in [node.left, *node.comparators]:
            _check(v)
        return None
    if isinstance(node, ast.IfExp):
        for v in (node.test, node.body, node.orelse):
            _check(v)
        return None
    if isinstance(node, (ast.Tuple, ast.List)):
        if len(node.elts) > 100:
            no("a list is at most 100 values")
        for v in node.elts:
            _check(v)
        return None
    if isinstance(node, ast.Subscript):
        _check(node.value)
        parts = [node.slice.lower, node.slice.upper, node.slice.step] if isinstance(node.slice, ast.Slice) else [node.slice]
        for part in parts:
            if part is None:
                continue
            number = part.operand if isinstance(part, ast.UnaryOp) and isinstance(part.op, ast.USub) else part
            if not (isinstance(number, ast.Constant) and type(number.value) is int):
                no("a position in [ ] is a whole number, e.g. [0], [-1] or [0:3]")
        return None
    if isinstance(node, ast.Call):
        if node.keywords or any(isinstance(a, ast.Starred) for a in node.args):
            no("write a function's values in order, without names, e.g. round(<<kW>>, 1)")
        if isinstance(node.func, ast.Name):
            if node.func.id not in FUNCTIONS:
                no(f"'{node.func.id}' is not an allowed function")
        elif isinstance(node.func, ast.Attribute):
            _check(node.func.value)  # first, so open('x').read() names open
            if node.func.attr not in METHODS:
                no(f"'.{node.func.attr}()' is not an allowed text function")
            if node.func.attr in _PAD and not (node.args and isinstance(node.args[0], ast.Constant)
                                                and type(node.args[0].value) is int and 0 <= node.args[0].value <= MAX_WIDTH):
                no(f".{node.func.attr}() takes a width from 0 to {MAX_WIDTH}, written as a number")
        else:
            no("only the allowed functions can be called")
        for a in node.args:
            _check(a)
        return None
    if isinstance(node, ast.Attribute):
        no(f"'.{node.attr}' is not allowed: a text function is written with brackets, e.g. <<Tag>>.upper()")
    if isinstance(node, ast.JoinedStr):
        no("f-strings are not allowed: use '%.1f kW' % <<kW>>")
    if isinstance(node, (ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
        no("functions and loops can't be written in an expression")
    if isinstance(node, (ast.Dict, ast.Set)):
        no("{ } is not allowed")
    if isinstance(node, ast.NamedExpr):
        no(":= is not allowed")
    no(f"{type(node).__name__} is not allowed")


def check_expression(code: str) -> str | None:
    """What isn't allowed in an expression (with its columns already as _c0, _c1, ...), or None."""
    try:
        prepare(code)
    except (NotAllowed, SyntaxError) as exc:
        return str(exc.msg if isinstance(exc, SyntaxError) and exc.msg else exc)
    return None


class _Guard(ast.NodeTransformer):
    """Sends % and the text functions through the guards in make_interpreter()."""

    def visit_BinOp(self, node: ast.BinOp) -> ast.AST:
        self.generic_visit(node)
        if isinstance(node.op, ast.Mod):
            return ast.Call(func=ast.Name("__mod", ast.Load()), args=[node.left, node.right], keywords=[])
        return node

    def visit_Call(self, node: ast.Call) -> ast.AST:
        self.generic_visit(node)
        if isinstance(node.func, ast.Attribute):
            return ast.Call(func=ast.Name("__text", ast.Load()), args=[node.func.value, ast.Constant(node.func.attr), *node.args],
                            keywords=[])
        return node


def prepare(code: str) -> str:
    """The expression checked and rewritten for the interpreter; raises NotAllowed (and
    SyntaxError for an expression that can't be read)."""
    if len(code) > MAX_EXPRESSION:
        raise NotAllowed(f"an expression is at most {MAX_EXPRESSION} characters")
    try:
        tree = ast.parse(code, mode="eval")
    except SyntaxError as exc:
        raise SyntaxError(f"can't be read: {exc.msg}") from exc
    _check(tree)
    return ast.unparse(ast.fix_missing_locations(_Guard().visit(tree)))


def _mod(left: object, right: object) -> object:
    """% : the remainder of numbers, or values written into text with every width and precision bounded."""
    if isinstance(left, str):
        for width, precision in _SPEC.findall(left):
            for n in (width, precision):
                if n == "*" or (n and int(n) > MAX_WIDTH):
                    raise ValueError(f"a % format's width is at most {MAX_WIDTH}")
    return left % right  # type: ignore[operator]


def _text(value: object, name: str, *args: object) -> object:
    """A text function of METHODS, on text only, with what it builds bounded."""
    if name not in METHODS:
        raise ValueError(f"{name} is not an allowed text function")
    if not isinstance(value, str):
        raise TypeError(f".{name}() works on text: use str(…) first")
    if name in _PAD and (not args or type(args[0]) is not int or not 0 <= args[0] <= MAX_WIDTH):  # type: ignore[operator]
        raise ValueError(f".{name}() takes a width from 0 to {MAX_WIDTH}")
    if name == "replace" and len(args) >= 2 and isinstance(args[0], str) and isinstance(args[1], str):
        times = value.count(args[0]) if args[0] else len(value) + 1
        if len(value) + times * len(args[1]) > MAX_RESULT:
            raise ValueError("the result would be too long")
    return getattr(value, name)(*args)


def make_interpreter() -> Interpreter:
    """An interpreter that offers nothing but FUNCTIONS, NAMES and the guards. Expressions must
    have been through prepare() first."""
    ai = Interpreter(use_numpy=False)
    ai.symtable.clear()
    ai.symtable.update(FUNCTIONS)
    ai.symtable.update(NAMES)
    ai.symtable.update({"__mod": _mod, "__text": _text})
    return ai


#: The row the help's examples are worked out on.
SAMPLE_ROW: dict[str, str] = {"Tag": "P-101", "Desc": " Feed pump A ", "Type": "DOL", "kW": "7.5", "Qty": "2", "Area": "100"}

#: (group, what the group is about, [(expression, result as written to the cell, what it does)])
FUNCTION_HELP: list[tuple[str, str, list[tuple[str, str, str]]]] = [
    ("Columns and values",
     "A column is written <<Column name>>. Its value is a number when it looks like one, otherwise text. "
     "In Then, Else if and Else, plain text such as Motor is used as it is.",
     [("<<kW>>", "7.5", "a column's value (here a number)"),
      ("<<Tag>>", "P-101", "a column's value (here text)"),
      ('"<<kW>>"', "7.5", "in quotes: always text, even when it looks like a number"),
      ("'Pump'", "Pump", "text, in quotes ('…' or \"…\")"),
      ("Motor", "Motor", "plain text in a value: used as it is"),
      ("True", "TRUE", "True and False; a result of True or False is written TRUE or FALSE")]),
    ("Comparisons and logic",
     "Conditions (If, Else if) are true or false. Text compares exactly: capitals count.",
     [("<<kW>> >= 7.5", "TRUE", "== equal, != not equal, < <= > >="),
      ("<<Type>> == 'DOL'", "TRUE", "text equal to"),
      ("<<Type>> in ('DOL', 'VSD')", "TRUE", "one of a list of values"),
      ("<<Type>> not in ('DOL', 'VSD')", "FALSE", "none of a list of values"),
      ("'pump' in <<Desc>>.lower()", "TRUE", "contains (here ignoring capitals)"),
      ("<<kW>> > 5 and <<Type>> == 'DOL'", "TRUE", "and, or, not combine conditions"),
      ("not <<Tag>>", "FALSE", "true when the cell is blank"),
      ("2 < <<kW>> <= 10", "TRUE", "a range, in one go"),
      ("'Large' if <<kW>> > 50 else 'Small'", "Small", "a choice inside a value: A if condition else B")]),
    ("Numbers",
     "Arithmetic as on a calculator. Comparing or adding a blank cell to a number is an error: check for blanks first.",
     [("<<kW>> * <<Qty>>", "15", "+ add, - subtract, * multiply, / divide"),
      ("<<Qty>> ** 2", "4", "** to the power of"),
      ("7 // 2", "3", "// whole-number division"),
      ("7 % 2", "1", "% remainder"),
      ("round(<<kW>> * 0.746, 1)", "5.6", "round to a number of decimals (a half goes to the even digit: round(2.5) is 2)"),
      ("round(<<kW>>)", "8", "round to a whole number"),
      ("ceil(<<kW>>)", "8", "round up"),
      ("floor(<<kW>>)", "7", "round down"),
      ("trunc(-7.5)", "-7", "drop the decimals"),
      ("abs(-3)", "3", "without its sign"),
      ("min(<<kW>>, 5)", "5", "the smallest of several"),
      ("max(<<kW>>, 10)", "10", "the largest of several"),
      ("sqrt(<<kW>> * 2)", "3.872983346", "square root"),
      ("log10(1000)", "3", "logarithm: log10 base 10, log natural (log(x, base) for another base)"),
      ("exp(0)", "1", "e to the power of"),
      ("pi * 2", "6.283185307", "pi and e"),
      ("sin(radians(30))", "0.5", "sin, cos, tan take radians; radians() and degrees() convert angles"),
      ("int('42')", "42", "text to a whole number"),
      ("float('7.25')", "7.25", "text to a number with decimals"),
      ("str(<<Area>>) + '-' + <<Tag>>", "100-P-101", "a number to text, to join it to text")]),
    ("Text",
     "Text functions are written after the text: <<Desc>>.strip(). Positions count from 0.",
     [("<<Tag>> + '-M'", "P-101-M", "+ joins text"),
      ("<<Desc>>.strip()", "Feed pump A", "remove spaces at both ends (lstrip: the start, rstrip: the end)"),
      ("<<Desc>>.upper()", " FEED PUMP A ", "capitals (lower: small letters, title: Each Word, capitalize: First letter)"),
      ("<<Tag>>.replace('-', '')", "P101", "replace every occurrence"),
      ("<<Tag>>.startswith('P')", "TRUE", "begins with (endswith(…): ends with)"),
      ("<<Tag>>.split('-')[0]", "P", "the part before a separator ([1]: after it)"),
      ("<<Tag>>[0:1]", "P", "characters by position: [0:3] the first three, [-2:] the last two"),
      ("len(<<Tag>>)", "5", "the number of characters"),
      ("<<Tag>>.find('-')", "1", "where some text is (-1 when it isn't there)"),
      ("<<Desc>>.count('p')", "2", "how many times some text occurs"),
      ("str(<<Area>>).zfill(5)", "00100", "pad with zeros on the left to a width (at most 1000)"),
      ("'%.1f kW' % <<kW>>", "7.5 kW", "a number written into text, with a number of decimals"),
      ("'%s x %s' % (<<Qty>>, <<Type>>)", "2 x DOL", "several values written into text"),
      ("<<Tag>>.isdigit()", "FALSE", "only digits (isalpha: only letters)"),
      ("<<Type>>.ljust(5, '.')", "DOL..", "pad on the right to a width (rjust: on the left)")]),
]


def auto_column_problems(col) -> list[str]:
    """What isn't allowed in a calculated column (an AutoColumn), each as "<field>: <why>". A
    condition must be allowed; a value must be allowed only when it refers to a column (else it is
    plain text, used as it is and never run)."""
    ref = re.compile(r"""(["']?)<<(.+?)>>\1""")
    out = []
    cases = [("If", col.statement, "Then", col.true_val)]
    cases += [(f"Else if {n} condition", b.statement, f"Else if {n} then", b.value) for n, b in enumerate(col.else_ifs, start=1)]
    fields = [(w, t, True) for w, t, _v, _x in cases] + [(v, x, False) for _w, _t, v, x in cases] + [("Else", col.false_val, False)]
    for where, text, is_condition in fields:
        names: list[str] = []
        code = ref.sub(lambda m: f"_c{names.append(m.group(2)) or len(names) - 1}", text or "").strip()
        if not code or (not is_condition and not names):  # blank, or a value that is plain text: never run
            continue
        problem = check_expression(code)
        if problem:
            out.append(f"{where}: {problem}")
    return out
