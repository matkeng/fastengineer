# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Deliverables: the lists a project issues (cable schedules, instrument lists, ...).

A deliverable takes its content from a generator's builds, optionally keeping only the rows
whose value in one output column is one of a set. A revision (A, B, ... Z, AA, ...) is a
frozen copy of that content, made when the user issues it; it is compared with the revision
before it. Revisions can't be edited; the latest one of a deliverable can be withdrawn."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from .generators.diff import change_report
from .generators.models import BuildResult, ChangeReport
from .generators.text import to_text
from .refdata.models import RefValidationError, new_id
from .refdata.validate import name_key

DeliverableType = Literal["Cable Schedule", "Instrument List", "PLC I/O List", "Equipment List", "Load List",
                          "Distribution Panel"]
DELIVERABLE_TYPES: list[str] = ["Cable Schedule", "Instrument List", "PLC I/O List", "Equipment List", "Load List",
                                "Distribution Panel"]
#: The type whose content is one panel's schedule from the Distribution Panels list (source "panel").
PANEL_TYPE = "Distribution Panel"


class Deliverable(BaseModel):
    id: str = Field(default_factory=new_id)
    type: DeliverableType
    name: str
    doc_number: str = ""
    doc_title: str = ""
    #: "generator": a build of `generator_id`. "project": generated from the Project Load List
    #: and the load types, by the list of this deliverable's type (keylists.loadgen).
    #: "panel": the schedule of the distribution panel `panel_id` (keylists.distribution_panels).
    source: Literal["generator", "project", "panel"] = "generator"
    generator_id: str = ""
    panel_id: str = ""
    filter_column: str = ""  # blank: every row
    filter_values: list[str] = Field(default_factory=list)
    #: The columns to keep, in the order to show them. Empty: every column, in the content's order.
    columns: list[str] = Field(default_factory=list)
    updated_at: datetime | None = None


class RevisionInfo(BaseModel):
    id: str = Field(default_factory=new_id)
    deliverable_id: str
    letter: str
    issued_at: datetime
    issued_by: str = ""
    description: str = ""
    build_seq: int  # the generator build it was made from
    rows: int = 0  # rows of content (separator rows not counted)
    added: int | None = None  # against the revision before; None for the first
    removed: int | None = None
    changed: int | None = None


class Revision(BaseModel):
    """A revision's frozen content, with what it needs to be shown, compared and exported later."""
    info: RevisionInfo
    result: BuildResult
    diff_key: str = ""
    doc_number: str = ""
    doc_title: str = ""
    filter_column: str = ""
    filter_values: list[str] = Field(default_factory=list)
    changes: ChangeReport | None = None
    #: Label and value lines frozen with the content (a distribution panel's header block).
    summary: list[tuple[str, str | int | float | None]] = Field(default_factory=list)


def next_letter(issued: list[str]) -> str:
    """The letter after the highest one issued: A, B, ... Z, AA, AB, ..."""
    def number(letter: str) -> int:
        n = 0
        for ch in letter.upper():
            n = n * 26 + (ord(ch) - 64)
        return n
    n = max((number(x) for x in issued if x.isalpha()), default=0) + 1
    out = ""
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


def content_rows(result: BuildResult) -> int:
    return sum(1 for r in result.rows if r.run_row_id is not None)


def apply_filter(result: BuildResult, column: str, values: list[str]) -> BuildResult:
    """Only the rows whose `column` is one of `values` (as text, ignoring case and extra spaces).
    Separator rows go. A blank column keeps everything; an unknown column is an error."""
    if not column.strip():
        return result
    names = [h.strip().casefold() for h in result.header]
    if column.strip().casefold() not in names:
        raise RefValidationError(f"The output has no column called '{column}'.", {"filter_column": "Not a column of the output"})
    i = names.index(column.strip().casefold())
    wanted = {name_key(v) for v in values}
    rows = [r for r in result.rows if r.run_row_id is not None and i < len(r.cells) and name_key(to_text(r.cells[i])) in wanted]
    return result.model_copy(update={"rows": rows, "changes": None})


def select_columns(result: BuildResult, columns: list[str]) -> BuildResult:
    """Only `columns`, in that order (named ignoring case and extra spaces). None chosen keeps
    the content as it is; a column the content doesn't have is an error."""
    if not columns:
        return result
    names = [h.strip().casefold() for h in result.header]
    missing = [c for c in columns if c.strip().casefold() not in names]
    if missing:
        raise RefValidationError(f"The content has no column called {', '.join(missing)}.", {"columns": "Not columns of the content"})
    picks = [names.index(c.strip().casefold()) for c in columns]
    rows = [r.model_copy(update={"cells": [r.cells[i] if i < len(r.cells) else None for i in picks]}) for r in result.rows]
    return result.model_copy(update={"header": [result.header[i] for i in picks], "rows": rows, "changes": None})


def compare(previous: Revision | None, result: BuildResult, diff_key: str) -> ChangeReport | None:
    """What changed from the previous revision to `result` (None when there is no previous)."""
    if previous is None:
        return None
    return change_report(previous.result.header, previous.result.rows, result.header, result.rows, diff_key)


def check_deliverable(d: Deliverable, others: list[Deliverable], generators: set[str], columns: list[str] | None,
                      panels: set[str] | None = None, key_column: str = "") -> Deliverable:
    """Trimmed and checked: the name is required and unique, the generator exists, and a
    filter names a column of the generator's output (`columns`; None when not known yet)
    and at least one value. A Distribution Panel deliverable takes its content from one of
    the `panels` (ids of the Distribution Panels list; None when not known), nothing else does.
    The columns chosen are columns of the content, once each, and include `key_column` (the
    column revisions are compared by) when that is known."""
    errors: dict[str, str] = {}
    d = d.model_copy(update={"name": d.name.strip(), "doc_number": d.doc_number.strip(), "doc_title": d.doc_title.strip(),
                             "filter_column": d.filter_column.strip(),
                             "filter_values": list(dict.fromkeys(v.strip() for v in d.filter_values if v.strip())),
                             "columns": list({name_key(c): c.strip() for c in d.columns if c.strip()}.values())})
    if not d.name:
        errors["name"] = "Name is required"
    elif any(o.id != d.id and name_key(o.name) == name_key(d.name) for o in others):
        errors["name"] = "Another deliverable has this name"
    if d.type == PANEL_TYPE:
        d = d.model_copy(update={"source": "panel", "generator_id": ""})
        if panels is not None and d.panel_id not in panels:
            errors["panel_id"] = "Choose a distribution panel"
    elif d.source == "panel":
        errors["source"] = "Only a Distribution Panel deliverable takes its content from a panel"
    elif d.source == "project":
        d = d.model_copy(update={"generator_id": "", "panel_id": ""})
    elif d.generator_id not in generators:
        errors["generator_id"] = "Choose a generator"
    else:
        d = d.model_copy(update={"panel_id": ""})
    if d.filter_column:
        if columns is not None and d.filter_column.casefold() not in [c.strip().casefold() for c in columns]:
            errors["filter_column"] = "Not a column of the generator's output"
        if not d.filter_values:
            errors["filter_values"] = "Give at least one value to keep"
    else:
        d = d.model_copy(update={"filter_values": []})
    if d.columns and columns is not None:
        known = {name_key(c): c for c in columns}
        unknown = [c for c in d.columns if name_key(c) not in known]
        if unknown:
            errors["columns"] = f"Not columns of the content: {', '.join(unknown)}"
        elif key_column and name_key(key_column) not in {name_key(c) for c in d.columns}:
            errors["columns"] = f"Keep the {key_column} column: revisions are compared by it"
        else:
            d = d.model_copy(update={"columns": [known[name_key(c)] for c in d.columns]})
    if errors:
        raise RefValidationError(f"{len(errors)} problem(s) in the deliverable.", errors)
    return d
