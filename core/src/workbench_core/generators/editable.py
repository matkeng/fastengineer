# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Stored forms of a generator and its builds.

A generator is stored as its editable document (config, runsheet, templates, parents...) plus
its reference tables, which are large and read-only until they move to shared reference data."""

from __future__ import annotations

import hashlib
from datetime import datetime

from pydantic import BaseModel, Field

from .models import BuildResult, BuildStats, Finding, Generator, RefTable
from .xlsx_import import ImportReport


class TableSummary(BaseModel):
    name: str
    columns: int
    rows: int


class GenRecord(BaseModel):
    """What the app edits. `generator.tables` is always empty here; see `tables`."""
    id: str
    name: str
    kind: str
    source_file: str = ""
    updated_at: datetime | None = None
    generator: Generator
    tables: list[TableSummary] = Field(default_factory=list)
    import_report: ImportReport | None = None


class GenSummary(BaseModel):
    id: str
    name: str
    kind: str
    source_file: str = ""
    updated_at: datetime | None = None
    runs: int = 0
    templates: int = 0
    last_build: "BuildInfo | None" = None


class BuildInfo(BaseModel):
    id: str
    generator_id: str
    seq: int
    created_at: datetime
    input_hash: str
    engine_version: str
    run_from: float | None = None
    run_up_to: float | None = None
    stats: BuildStats
    warnings: list[Finding] = Field(default_factory=list)
    unresolved_count: int = 0
    unresolved_tokens: list[str] = Field(default_factory=list)
    added: int | None = None  # None: no previous build to compare with
    removed: int | None = None
    changed: int | None = None


class BuildRecord(BaseModel):
    info: BuildInfo
    result: BuildResult


def split(gen: Generator) -> tuple[Generator, dict[str, RefTable]]:
    """(editable generator without tables, tables)."""
    return gen.model_copy(update={"tables": {}}), dict(gen.tables)


def merge(gen: Generator, tables: dict[str, RefTable]) -> Generator:
    return gen.model_copy(update={"tables": tables})


def summarise(tables: dict[str, RefTable]) -> list[TableSummary]:
    return [TableSummary(name=n, columns=len(t.columns), rows=len(t.rows)) for n, t in sorted(tables.items())]


def input_hash(gen: Generator, tables: dict[str, RefTable], run_from: float | None, run_up_to: float | None) -> str:
    """Identifies a build's inputs (generator document, tables and run range)."""
    h = hashlib.sha256()
    h.update(gen.model_copy(update={"tables": {}}).model_dump_json().encode())
    for name in sorted(tables):
        h.update(name.encode())
        h.update(tables[name].model_dump_json().encode())
    h.update(f"{run_from}|{run_up_to}".encode())
    return h.hexdigest()


GenSummary.model_rebuild()
