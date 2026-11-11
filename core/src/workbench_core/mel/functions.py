# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""What a calculated column's expressions can use, and the help the List import page shows.

Expressions are evaluated by asteval (a safe subset of Python). The interpreter is made here,
without the few built-ins that reach outside the row: `open` (it reads files on the engine's
machine, which a recipe passed between people must not), `print` and `dir`.

FUNCTION_HELP is what the page lists. Every example in it is run by the tests against SAMPLE_ROW,
so the result shown next to it is what the app really gives.
"""

from __future__ import annotations

from asteval import Interpreter

#: Built-ins that are not offered: they reach outside the row (files, output) or say nothing useful.
REMOVED = ("open", "print", "dir")

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
      ("pow(<<kW>>, 2)", "56.25", "to the power of"),
      ("log10(1000)", "3", "logarithm (log for natural, log10 for base 10)"),
      ("pi * 2", "6.283185307", "pi and e"),
      ("sin(radians(30))", "0.5", "sin cos tan, radians and degrees convert angles"),
      ("int('42')", "42", "text to a whole number"),
      ("float('7.25')", "7.25", "text to a number with decimals"),
      ("str(<<Area>>) + '-' + <<Tag>>", "100-P-101", "a number to text, to join it to text")]),
    ("Text",
     "Text functions are written after the text: <<Desc>>.strip(). Positions count from 0.",
     [("<<Tag>> + '-M'", "P-101-M", "+ joins text"),
      ("<<Desc>>.strip()", "Feed pump A", "remove spaces at both ends"),
      ("<<Desc>>.upper()", " FEED PUMP A ", "capitals (lower() small letters, title() Each Word)"),
      ("<<Tag>>.replace('-', '')", "P101", "replace every occurrence"),
      ("<<Tag>>.startswith('P')", "TRUE", "begins with (endswith(…): ends with)"),
      ("<<Tag>>.split('-')[0]", "P", "the part before a separator ([1]: after it)"),
      ("<<Tag>>[0:1]", "P", "characters by position: [0:3] the first three, [-2:] the last two"),
      ("len(<<Tag>>)", "5", "the number of characters"),
      ("<<Tag>>.find('-')", "1", "where some text is (-1 when it isn't there)"),
      ("<<Desc>>.count('p')", "2", "how many times some text occurs"),
      ("str(<<Area>>).zfill(5)", "00100",
       "pad with zeros to a width (rjust and ljust pad with any character)"),
      ("'%.1f kW' % <<kW>>", "7.5 kW", "a number written into text, with a number of decimals"),
      ("'%s x %s' % (<<Qty>>, <<Type>>)", "2 x DOL", "several values written into text"),
      ("<<Tag>>.isdigit()", "FALSE", "only digits (isalpha: only letters)")]),
]


def make_interpreter() -> Interpreter:
    """An interpreter for calculated columns, without the built-ins in REMOVED."""
    ai = Interpreter(use_numpy=False)
    for name in REMOVED:
        ai.symtable.pop(name, None)
    return ai
