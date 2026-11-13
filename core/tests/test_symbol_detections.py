# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""The detections table: one row per symbol found, with its centre in mm (PID Symbols)."""

from __future__ import annotations

from workbench_core.mel.models import fields_for, is_load_target, output_name
from workbench_core.symbols.models import FoundTag, PageResult, Symbol
from workbench_core.symbols.pipeline import SheetResult, detections_table


def _page() -> PageResult:
    return PageResult(page=2, symbols=[
        Symbol(template_id="t", template_desc="Instrument bubble", box=[200, 400, 400, 600], score=0.912, tag="FT-101"),
        Symbol(template_id="v", template_desc="Valve", box=[1000, 1000, 1100, 1050], score=0.8),  # no tag
        Symbol(template_id="t", template_desc="Instrument bubble", box=[210, 410, 410, 610], score=0.85, tag="FT-101"),
    ], tags=[FoundTag(tag="FT-101", groups={"function": "FT", "loop": "101"}, source="template", box=[200, 400, 400, 600]),
             FoundTag(tag="PT-7", groups={"function": "PT"}, source="pattern", box=[0, 0, 20, 10])])


def test_one_row_per_detection_with_its_centre_in_mm() -> None:
    headers, rows = detections_table([SheetResult("pid-1.pdf", _page())], ["function", "loop"])
    assert headers == ["Key", "Drawing", "Page", "Tag", "function", "loop", "Symbol", "Source", "Score", "X (mm)", "Y (mm)",
                       "Width (mm)", "Height (mm)"]
    assert len(rows) == 4  # three symbols (one with no tag) and the text-scan tag
    a = rows[0]
    assert (a["Tag"], a["function"], a["Symbol"], a["Source"], a["Score"]) == ("FT-101", "FT", "Instrument bubble", "template", "0.912")
    assert (a["X (mm)"], a["Y (mm)"], a["Width (mm)"], a["Height (mm)"]) == ("38.1", "63.5", "25.4", "25.4")  # px at 200 DPI
    assert rows[1]["Tag"] == "" and rows[1]["Symbol"] == "Valve" and rows[3]["Source"] == "text scan" and rows[3]["Score"] == ""
    # keys: stable for the same symbol in the same place, unique
    assert a["Key"] == "pid-1.pdf p2 FT-101 @38,64" and len({r["Key"] for r in rows}) == 4
    again = detections_table([SheetResult("pid-1.pdf", _page())], ["function", "loop"])[1]
    assert [r["Key"] for r in again] == [r["Key"] for r in rows]


def test_the_pid_symbols_import_type() -> None:
    assert not is_load_target("PSL") and not is_load_target("PIL") and is_load_target("MEL")
    assert output_name("PSL") == "PID Symbols" and {"x_mm", "y_mm", "drawing", "page", "symbol"} <= set(fields_for("PSL"))
