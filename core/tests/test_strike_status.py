# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""How much of a MEL row is struck through (mel.ingest.strike_status)."""

from workbench_core.excel.models import CellOut
from workbench_core.mel.ingest import strike_status


def _row(*cells: tuple[str, str]) -> list[CellOut]:
    return [CellOut(v=t, t=t, s=s) for t, s in cells]


def test_strike_status() -> None:
    assert strike_status(_row(("P-1", "none"), ("Pump", "none"))) == ""
    assert strike_status(_row(("P-1", "full"), ("Pump", "full"), ("", "none"))) == "Full Row"  # blank cells don't count
    assert strike_status(_row(("P-1", "none"), ("Pump", "full"), ("5", "full"))) == "Multiple Cells"
    assert strike_status(_row(("P-1", "none"), ("Pump", "full"), ("5", "partial"))) == "Multiple Cells"
    assert strike_status(_row(("P-1", "none"), ("Pump", "full"), ("5", "none"))) == "One Cell"
    assert strike_status(_row(("P-1", "none"), ("Pump", "partial"), ("5", "partial"))) == "Partial Cell/s"
    assert strike_status([]) == ""
