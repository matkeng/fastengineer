# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""A small, safe expression language for late formulas (PRD 7.3). No eval.

Grammar (Excel precedence, lowest first):
    comparison  = , <>, <, >, <=, >=
    concat      &
    additive    + -
    term        * /
    power       ^
    unary       -  +
    primary     number | "string" | TRUE | FALSE | FUNC(args) | (expr) | [Column]

Functions: ROUND, CEILING, MAX, MIN, IF, LEN, UPPER, LOWER, TRIM, LEFT, RIGHT, CONCAT.
Text and numbers convert like Excel: "&" turns numbers into text, arithmetic turns
numeric text into numbers (else #VALUE!)."""

from __future__ import annotations

import math
import re
from collections.abc import Callable

from .text import number_text


class ExprError(ValueError):
    pass


_TOKEN = re.compile(r"""
    \s*(?:
      (?P<num>\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?)
    | (?P<str>"(?:[^"]|"")*")
    | (?P<ref>\[[^\]]*\])
    | (?P<name>[A-Za-z_][A-Za-z0-9_.]*)
    | (?P<op><>|<=|>=|[-+*/^&(),=<>])
    )""", re.VERBOSE)


def tokenize(src: str) -> list[tuple[str, str]]:
    out, i = [], 0
    src = src.rstrip()
    while i < len(src):
        m = _TOKEN.match(src, i)
        if not m or m.end() == i:
            raise ExprError(f"Unexpected character at {i + 1}: {src[i:i + 10]!r}")
        kind = m.lastgroup
        out.append((kind, m.group(kind)))
        i = m.end()
    out.append(("end", ""))
    return out


def _num(v):
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if v is None or v == "":
        return 0.0
    try:
        return float(str(v).strip())
    except ValueError as exc:
        raise ExprError(f"#VALUE! ({v!r} is not a number)") from exc


def _text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, (int, float)):
        return number_text(v)
    return str(v)


def _norm(v):
    """Numbers come out as int when whole (Excel shows 75, not 75.0)."""
    if isinstance(v, float) and v == int(v) and abs(v) < 1e15:
        return int(v)
    return v


def _round(x, n=0):
    x, n = _num(x), int(_num(n))
    q = 10 ** n
    return math.floor(abs(x) * q + 0.5) / q * (1 if x >= 0 else -1)  # Excel rounds half away from zero


def _ceiling(x, sig=1):
    x, sig = _num(x), _num(sig)
    return 0.0 if sig == 0 else math.ceil(x / sig) * sig


FUNCS: dict[str, Callable] = {
    "ROUND": _round,
    "CEILING": _ceiling,
    "MAX": lambda *a: max(_num(x) for x in a),
    "MIN": lambda *a: min(_num(x) for x in a),
    "LEN": lambda s: float(len(_text(s))),
    "UPPER": lambda s: _text(s).upper(),
    "LOWER": lambda s: _text(s).lower(),
    "TRIM": lambda s: " ".join(_text(s).split()),
    "LEFT": lambda s, n=1: _text(s)[: int(_num(n))],
    "RIGHT": lambda s, n=1: _text(s)[-int(_num(n)):] if int(_num(n)) else "",
    "CONCAT": lambda *a: "".join(_text(x) for x in a),
}

_BIN = {  # op: (left binding power, right binding power)
    "=": (1, 2), "<>": (1, 2), "<": (1, 2), ">": (1, 2), "<=": (1, 2), ">=": (1, 2),
    "&": (3, 4),
    "+": (5, 6), "-": (5, 6),
    "*": (7, 8), "/": (7, 8),
    "^": (10, 9),
}


def _compare(op, a, b):
    if isinstance(a, str) or isinstance(b, str):
        a, b = _text(a).lower(), _text(b).lower()
    else:
        a, b = _num(a), _num(b)
    return {"=": a == b, "<>": a != b, "<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b}[op]


class _Parser:
    def __init__(self, tokens, refs: Callable[[str], object] | None):
        self.t, self.i, self.refs = tokens, 0, refs

    def peek(self):
        return self.t[self.i]

    def next(self):
        tok = self.t[self.i]
        self.i += 1
        return tok

    def expect(self, value):
        kind, v = self.next()
        if v != value:
            raise ExprError(f"Expected {value!r}, found {v or 'end'!r}")

    def parse(self, rbp=0):
        left = self.prefix()
        while True:
            kind, op = self.peek()
            if kind != "op" or op not in _BIN or _BIN[op][0] <= rbp:
                return left
            self.next()
            right = self.parse(_BIN[op][1])
            left = self.binary(op, left, right)

    def binary(self, op, a, b):
        if op == "&":
            return _text(a) + _text(b)
        if op in ("=", "<>", "<", ">", "<=", ">="):
            return _compare(op, a, b)
        x, y = _num(a), _num(b)
        if op == "+":
            return x + y
        if op == "-":
            return x - y
        if op == "*":
            return x * y
        if op == "/":
            if y == 0:
                raise ExprError("#DIV/0!")
            return x / y
        return x ** y

    def prefix(self):
        kind, v = self.next()
        if kind == "num":
            return float(v)
        if kind == "str":
            return v[1:-1].replace('""', '"')
        if kind == "ref":
            if self.refs is None:
                raise ExprError(f"Column references are not allowed here: {v}")
            return self.refs(v[1:-1])
        if kind == "op" and v in ("-", "+"):
            x = _num(self.parse(10))  # Excel: unary minus binds tighter than ^ (-2^2 = 4)
            return -x if v == "-" else x
        if kind == "op" and v == "(":
            e = self.parse()
            self.expect(")")
            return e
        if kind == "name":
            up = v.upper()
            if up == "TRUE":
                return True
            if up == "FALSE":
                return False
            if self.peek()[1] != "(":
                raise ExprError(f"Unknown name {v!r}")
            self.next()
            args = []
            if self.peek()[1] != ")":
                while True:
                    args.append(self.parse())
                    if self.peek()[1] == ",":
                        self.next()
                        continue
                    break
            self.expect(")")
            if up == "IF":
                if not 2 <= len(args) <= 3:
                    raise ExprError("IF takes 2 or 3 arguments")
                cond = args[0]
                truth = cond if isinstance(cond, bool) else _num(cond) != 0
                return args[1] if truth else (args[2] if len(args) == 3 else False)
            if up not in FUNCS:
                raise ExprError(f"Unknown function {v}")
            try:
                return FUNCS[up](*args)
            except TypeError as exc:
                raise ExprError(f"Wrong number of arguments for {up}") from exc
        raise ExprError(f"Unexpected {v or 'end of formula'!r}")


def evaluate(src: str, refs: Callable[[str], object] | None = None):
    """Evaluate a formula (with or without the leading '=')."""
    s = src.strip()
    if s.startswith("="):
        s = s[1:]
    p = _Parser(tokenize(s), refs)
    v = p.parse()
    if p.peek()[0] != "end":
        raise ExprError(f"Unexpected {p.peek()[1]!r}")
    return _norm(v)


def parses(src: str) -> bool:
    try:
        s = src.strip().lstrip("=")
        p = _Parser(tokenize(s), lambda name: 0)
        p.parse()
        return p.peek()[0] == "end"
    except ExprError:
        return False
