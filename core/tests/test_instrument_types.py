# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Instrument Types, and the PID Symbols' loops each given one."""

from __future__ import annotations

import pytest

from workbench_core.keylists.instrument_types import (check_instrument_types, default_instrument_types, parse_functions,
                                                      suggest_type)
from workbench_core.keylists.pid_loops import PidLoopState, PidLoopStates, loops_of
from workbench_core.refdata import RefValidationError

TYPES = default_instrument_types()


def _type(name: str):
    return next(t for t in TYPES if t.name == name)


def test_types_are_checked() -> None:
    assert parse_functions("de, dx  DIT;de") == ["DE", "DX", "DIT"] and parse_functions(["lt", "LIT"]) == ["LT", "LIT"]
    ok = check_instrument_types([{"name": " 2 x Conveyor  Drift Switch ", "functions": "zs, ZSA"}])
    assert (ok[0].name, ok[0].functions) == ("2 x Conveyor Drift Switch", ["ZS", "ZSA"])
    with pytest.raises(RefValidationError) as exc:
        check_instrument_types([{"id": "a", "name": "", "functions": "1X"}, {"id": "b", "name": "Level", "functions": "LT"},
                                {"id": "c", "name": "level", "functions": "LT, LIT"}])
    assert set(exc.value.fields) == {"a.name", "a.functions", "c.name", "c.functions"}
    assert len({t.id for t in TYPES}) == len(TYPES) and _type("Density Transmitter").functions == ["DE", "DX", "DIT"]


def test_a_loops_type_is_suggested_from_its_functions() -> None:
    assert suggest_type(["DE", "DIT"], TYPES).name == "Density Transmitter"
    assert suggest_type(["FT", "FV"], TYPES).name == "Flow Transmitter"  # a tie: fewer codes it doesn't have, then list order
    assert suggest_type(["XX"], TYPES) is None


def test_detections_grouped_by_loop() -> None:
    rows = [{"tag": "DIT-1100", "function": "DIT", "loop": "1100", "drawing": "b.pdf", "page": 1},
            {"tag": "DE-1100", "function": "DE", "loop": "1100", "drawing": "a.pdf", "page": 2},
            {"tag": "DIT-1100", "function": "DIT", "loop": "1100", "drawing": "a.pdf", "page": 2},
            {"tag": "LT-99", "function": "LT", "loop": "99", "drawing": "a.pdf", "page": 1},
            {"tag": "XY-7", "function": "XY", "loop": "7", "drawing": "a.pdf", "page": 1},
            {"tag": "", "function": "", "loop": "", "drawing": "a.pdf", "page": 1}]
    states = PidLoopStates(loops={"99": PidLoopState(type_id=_type("Pressure Gauge").id, verified=True), "7": PidLoopState(no_type=True)})
    loops = loops_of(rows, TYPES, states)
    assert [x.loop for x in loops] == ["7", "99", "1100"]  # natural order; no loop number left out
    d = loops[2]
    assert (d.functions, d.tags, d.drawings, d.detections) == (["DE", "DIT"], ["DE-1100", "DIT-1100"], ["a.pdf p2", "b.pdf p1"], 3)
    assert (d.type_name, d.type_by, d.verified) == ("Density Transmitter", "auto", False)
    assert (loops[1].type_name, loops[1].type_by, loops[1].suggested_id, loops[1].verified) == (
        "Pressure Gauge", "user", _type("Level Transmitter").id, True)
    assert (loops[0].type_id, loops[0].type_by) == (None, "user")  # "no type" chosen
