# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Data model for the deliverable generators (PRD section 11).

A generator turns a *runsheet* (one row per run) into an output table by copying the
*template* block selected by each run's key and filling in its <<TAG>> placeholders."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Union

from pydantic import BaseModel, Field

Scalar = Union[str, int, float, bool, date, datetime, None]
Mode = Literal["compat", "standard"]
GeneratorId = Literal["dp", "power", "instCable", "deviceList", "ioList"]


class GeneratorConfig(BaseModel):
    """Appendix A. Excel-only settings (CopyFormats, SaveAfterBuild, sheet names) are kept
    so imported configs round-trip, but the engine ignores them."""
    key_placeholder: str = "<<Key>>"
    run_placeholder: str = "<<RUN>>"
    locked_placeholder: str = "<<LOCKED>>"
    stop_at_blank_key: bool = False
    blank_row_between_runs: bool = True
    parent_include_tag: bool = False
    use_parents: bool = True
    collapse_spaces: bool = True
    replace_f_equals: bool = False
    freeze_formulas: bool = False
    run_from: float | None = None
    run_up_to: float | None = None  # exclusive (PRD 5.3; Appendix D item 2)
    keep_prev: bool = True
    diff_key: str = "Cable Number"
    run_column: str = "Run Num"
    doc_number: str = ""
    doc_title: str = ""
    doc_revision: str = ""
    date_format: str = "%d/%m/%Y"
    mode: Mode = "compat"
    extra: dict[str, str] = Field(default_factory=dict)  # unrecognised tblConfig settings, kept for round trip


DEFAULT_CONFIGS: dict[str, GeneratorConfig] = {
    "dp": GeneratorConfig(replace_f_equals=True, freeze_formulas=True),
    "power": GeneratorConfig(use_parents=False, collapse_spaces=False),
    "instCable": GeneratorConfig(key_placeholder="<<STD>>", freeze_formulas=True),
    "deviceList": GeneratorConfig(parent_include_tag=True, diff_key="Tag", run_column="Run"),
    "ioList": GeneratorConfig(parent_include_tag=True, diff_key="TAG", run_column="Run"),
}


class ColumnDef(BaseModel):
    name: str  # human label (runsheet row 1)
    tag: str | None = None  # "<<MECH>>" (row 2)
    source: str | None = None  # Power row 3: model | number | choice | builtin | text
    formula: str | None = None  # imported Excel formula of a computed runsheet column (values are cached)


class RunRow(BaseModel):
    id: str
    values: list[Scalar]  # by column position (tags may repeat case-insensitively only as an error)


class Runsheet(BaseModel):
    columns: list[ColumnDef]
    rows: list[RunRow] = Field(default_factory=list)


# -- computed columns (PRD 7.2) ------------------------------------------------------

class Concat(BaseModel):
    kind: Literal["concat"] = "concat"
    parts: list[str | dict]  # literal strings, or {"col": "Cable Range"}


class Exists(BaseModel):
    kind: Literal["exists"] = "exists"
    value: str  # output column name
    table: str
    column: str
    approximate: bool = True  # compat: EXACT(VLOOKUP(x, list, 1), x) with a sorted list


class Lookup(BaseModel):
    kind: Literal["lookup"] = "lookup"
    key: str  # output column name
    table: str
    key_column: str
    return_column: str
    if_key_blank: Literal["blank", "error", "lookup"] = "lookup"
    guard_column: str | None = None  # IF(<guard> <> "", VLOOKUP(...), "")


class Expr(BaseModel):
    kind: Literal["expr"] = "expr"
    expression: str  # may reference output columns as [Column Name]


class Count(BaseModel):
    kind: Literal["count"] = "count"
    table: str
    column: str
    equals: str  # output column name


Computed = Union[Concat, Exists, Lookup, Expr, Count]


class TemplateCell(BaseModel):
    """literal: a constant (type kept); text: contains tags; late: 'F=...' text;
    formula: an Excel formula not mapped to a computed column (kept as text, flagged);
    computed: the column's computed definition (or an override)."""
    kind: Literal["literal", "text", "late", "formula", "computed"]
    value: Scalar = None
    text: str | None = None
    override: Computed | None = Field(default=None, discriminator="kind")


class TemplateRow(BaseModel):
    cells: list[TemplateCell]  # by output column position (after TEMPLATE)
    source_row: int | None = None  # row on the Templates sheet, for traceability


class Template(BaseModel):
    id: str  # text of the ID (what runsheet keys are matched against)
    id_value: Scalar = None  # the ID as stored (a number or text); written to the TEMPLATE column
    rows: list[TemplateRow]
    duplicate_blocks: int = 0  # further blocks with the same ID (ignored; PRD 4.2)


class DerivedTag(BaseModel):
    name: str
    source: str
    transform: str = ""
    default: str = ""


class Route(BaseModel):
    a: str
    b: str
    length: float


class CablePrefix(BaseModel):
    cable_type: str
    prefix: str


class RefTable(BaseModel):
    """A lookup table. Columns are named; for Excel-style lookups the column letters of the
    source sheet are kept too, so VLOOKUP(x, Sheet!B:I, 6, 0) maps by position."""
    name: str
    columns: list[str]
    rows: list[list[Scalar]] = Field(default_factory=list)
    first_column: int = 1  # 1-based sheet column of columns[0]


class OutputColumn(BaseModel):
    name: str
    computed: Computed | None = Field(default=None, discriminator="kind")
    raw: bool = False  # cells are lookup keys written without tag expansion (the lookup table keys hold tag patterns)


class Generator(BaseModel):
    id: str
    name: str = ""
    config: GeneratorConfig = Field(default_factory=GeneratorConfig)
    runsheet: Runsheet
    id_column: str = "TEMPLATE"  # header of the template-ID column (first output column)
    output_columns: list[OutputColumn]  # after the ID column
    templates: list[Template] = Field(default_factory=list)
    derived_tags: list[DerivedTag] = Field(default_factory=list)
    routes: list[Route] = Field(default_factory=list)
    cable_prefixes: list[CablePrefix] = Field(default_factory=list)
    parents: list[tuple[str, str]] | None = None  # (tag, description); None = no Parents table
    tables: dict[str, RefTable] = Field(default_factory=dict)


# -- results -----------------------------------------------------------------------------

class Finding(BaseModel):
    severity: Literal["ERROR", "WARN", "INFO"]
    code: str  # C1..C20 or a build warning code
    item: str
    detail: str = ""
    where: str = ""


class OutputRow(BaseModel):
    cells: list[Scalar]  # TEMPLATE first, then output_columns
    run_row_id: str | None = None  # None for separator rows
    template_id: str | None = None
    template_seq: int | None = None
    locked: bool = False


class BuildStats(BaseModel):
    processed: int = 0  # runs that produced rows (expanded or copied from a locked run)
    skipped: int = 0  # key nr / none
    filtered: int = 0  # outside RunFrom..RunUpTo
    blank_key: int = 0
    no_template: int = 0
    deleted_rows: int = 0  # standard mode: rows dropped by <<DELETE ROW>>
    rows_written: int = 0  # generated rows, separators excluded
    output_rows: int = 0  # including separators
    non_empty_cells: int = 0
    locked_used: int = 0
    duration_ms: float = 0
    phase_ms: dict[str, float] = Field(default_factory=dict)


class ChangedCell(BaseModel):
    column: str
    old: Scalar = None
    new: Scalar = None


class ChangeEntry(BaseModel):
    key: str
    kind: Literal["added", "removed", "changed"]
    cells: list[ChangedCell] = Field(default_factory=list)


class ChangeReport(BaseModel):
    added: int = 0
    removed: int = 0
    changed: int = 0
    entries: list[ChangeEntry] = Field(default_factory=list)


class BuildResult(BaseModel):
    header: list[str]
    rows: list[OutputRow]
    stats: BuildStats
    warnings: list[Finding] = Field(default_factory=list)
    unresolved_tokens: list[str] = Field(default_factory=list)
    unresolved_count: int = 0
    changes: ChangeReport | None = None
    engine_version: str = ""


class BuildError(Exception):
    """A fatal build error, naming the stage (and run/row when known)."""

    def __init__(self, stage: str, message: str, run: str | None = None, row: int | None = None):
        where = f" (run {run})" if run is not None else ""
        where += f" (runsheet row {row})" if row is not None else ""
        super().__init__(f"{stage}: {message}{where}")
        self.stage, self.run, self.row = stage, run, row
