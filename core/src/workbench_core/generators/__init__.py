# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Deliverable generators: runsheet x templates -> cable schedules, device and IO lists.

Pure engine (no I/O except the explicit xlsx import/export helpers). See
`docs/GENERATORS.md` for the rules it reproduces (the Excel/VBA generator engine it replaces)."""

from .check import CheckResult, check
from .diff import change_report
from .expand import ENGINE_VERSION, build, discover_tags
from .models import (BuildError, BuildResult, DEFAULT_CONFIGS, Generator, GeneratorConfig, OutputRow)
from .text import NO_VALUE, PARENT_NOT_FOUND, to_text

__all__ = [
    "BuildError", "BuildResult", "CheckResult", "DEFAULT_CONFIGS", "ENGINE_VERSION", "Generator", "GeneratorConfig",
    "NO_VALUE", "OutputRow", "PARENT_NOT_FOUND", "build", "change_report", "check", "discover_tags", "to_text",
]
