# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Proper case keeping the project's xProper words: tag modifiers, expressions, the enum."""

from __future__ import annotations

from workbench_core.keylists.enums import EnumItem, check_enums, default_enums
from workbench_core.keylists.tag_paths import apply
from workbench_core.mel.functions import make_interpreter, prepare
from workbench_core.text_case import DEFAULT_PROPER_WORDS, PROPER_WORDS, proper_case, use_proper_words


def test_proper_case_keeps_the_words_as_written() -> None:
    assert proper_case("mcc-01 feed to plc i/o panel", DEFAULT_PROPER_WORDS) == "MCC-01 Feed To PLC I/O Panel"
    assert proper_case("P&ID for the Vsd", DEFAULT_PROPER_WORDS) == "P&ID For The VSD"
    assert proper_case("motor 7.5KW", ["kW"]) == "Motor 7.5kW"  # digits either side are fine
    assert proper_case("dcs and mccs", DEFAULT_PROPER_WORDS) == "Dcs And Mccs"  # not inside other words
    assert proper_case("o'clock 415v", []) == "O'clock 415V" and proper_case("SPARE  pump", []) == "Spare  Pump"


def test_the_words_of_the_context() -> None:
    assert proper_case("plc") == "PLC"  # no project: the defaults
    calls = []
    token = use_proper_words(lambda: calls.append(1) or ["VFD"])
    try:
        assert proper_case("vfd for plc") == "VFD For Plc" and proper_case("vfd") == "VFD"
        assert calls == [1]  # read once
        assert apply("vfd for plc", [("title", [])]) == "VFD For Plc" == apply("vfd for plc", [("proper", [])])
        ai = make_interpreter()
        assert ai(prepare("'vfd room'.title() + ' ' + proper('a vfd')")) == "VFD Room A VFD"
    finally:
        PROPER_WORDS.reset(token)


def test_the_xproper_enum() -> None:
    d = default_enums()
    assert [w.name for w in d.x_proper] == list(DEFAULT_PROPER_WORDS) and d.x_proper[0].id == "xp1"
    e = check_enums(d.model_copy(update={"x_proper": [EnumItem(id="w1", code="X", name=" VFD ")]}))
    assert (e.x_proper[0].code, e.x_proper[0].name) == ("", "VFD")
