# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""PLC hardware register: catalogue defaults, card names, checks and totals (invented data)."""

from workbench_core.generators.hardware import (Card, Catalogue, CardType, Hardware, Panel, Rack, RackType,
                                                check_hardware, default_catalogue, schedule, summarise)
from workbench_core.generators.models import BuildResult, BuildStats, OutputRow


def test_default_catalogue():
    cat = default_catalogue()
    kinds = {(t.kind, t.channels) for t in cat.card_types}
    assert ("Network", 0) in kinds
    for k in ["DI", "DO", "AI", "AO", "RTD"]:
        for n in [8, 12, 16, 32]:
            assert (k, n) in kinds
    assert len(cat.card_types) == 21 and len(cat.rack_types) == 1
    assert len({t.id for t in cat.card_types}) == 21
    assert next(t for t in cat.card_types if t.id == "ai8").wiring == "2/3/4-wire"


def hw_fixture() -> tuple[Hardware, Catalogue]:
    cat = default_catalogue()
    cat.card_types[1].part_number = "DI-8X"  # di8
    rack = Rack(number=1, rack_type_id="rack", cards=[Card(card_type_id="net"), Card(card_type_id="di8"), None,
                                                      Card(card_type_id="do16", tag="PNL1-DO-A", spare=True)])
    return Hardware(panels=[Panel(tag="PNL1", racks=[rack])]), cat


def test_schedule_names_and_slots():
    hw, cat = hw_fixture()
    rows = schedule(hw, cat)
    assert [(r.slot, r.card, r.kind, r.channels) for r in rows] == [
        (1, "PNL1-R1-S1", "Network", 0), (2, "PNL1-R1-S2", "DI", 8), (4, "PNL1-DO-A", "DO", 16)]
    assert rows[2].spare and rows[1].part_number == "DI-8X"
    hw.panels[0].racks[0].first_slot = 0
    assert schedule(hw, cat)[0].card == "PNL1-R1-S0"


def test_checks():
    hw, cat = hw_fixture()
    assert check_hardware(hw, cat) == []
    p = hw.panels[0]
    p.racks.append(Rack(number=1, rack_type_id="nope", cards=[Card(card_type_id="x"), Card(card_type_id="ai8")]))
    hw.panels.append(Panel(tag="pnl1"))
    cat.rack_types.append(RackType(id="small", max_slots=2))
    p.racks[0].rack_type_id = "small"
    codes = {f.code for f in check_hardware(hw, cat)}
    assert {"H1", "H2", "H3", "H4", "H5", "H6"} <= codes
    p.racks[0].cards[3].tag = "PNL1-R1-S2"  # clashes with the generated name of slot 2
    assert "H7" in {f.code for f in check_hardware(hw, cat)}


def test_summary_against_io_list():
    hw, cat = hw_fixture()
    build = BuildResult(header=["TEMPLATE", "TAG", "CARD TYPE"], stats=BuildStats(), rows=[
        OutputRow(cells=[1, "A", "DI-8X"], run_row_id="1"), OutputRow(cells=[1, "B", "di-8x"], run_row_id="1"),
        OutputRow(cells=[None, None, None]),
        OutputRow(cells=[2, "C", "OTHER"], run_row_id="2")])
    s = summarise(hw, cat, build)
    assert (s.panels, s.racks, s.cards) == (1, 1, 3)
    assert {k.kind: (k.cards, k.channels, k.spare_cards) for k in s.by_kind} == {
        "Network": (1, 0, 0), "DI": (1, 8, 0), "DO": (1, 16, 1)}
    d = {x.card_type: x for x in s.demand}
    assert (d["DI-8X"].points, d["DI-8X"].kind, d["DI-8X"].channels, d["DI-8X"].free) == (1, "DI", 8, 7)
    assert d["di-8x"].channels == 8  # part numbers match case-insensitively
    assert d["OTHER"].kind is None and d["OTHER"].free == -1
    assert s.demand_column == "CARD TYPE"
    assert summarise(hw, cat).demand == []


def test_roundtrip_json():
    hw, cat = hw_fixture()
    assert Hardware.model_validate_json(hw.model_dump_json()) == hw
    assert Catalogue.model_validate_json(cat.model_dump_json()) == cat
    assert CardType(kind="AI", channels=8).id  # generated id
