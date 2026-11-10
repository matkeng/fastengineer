# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""The PLC List: IO points follow the card types, the checks, the old register's shape, the
move from the generators' registers, and the workbook."""

from workbench_core.generators.hardware import Card, Hardware, Panel, Rack, default_catalogue, schedule
from workbench_core.keylists.plc import (PlcCard, PlcList, PlcRack, PlcSystem, as_hardware, check_plc, from_registers,
                                         normalise_points, read_workbook, write_workbook)

CAT = default_catalogue()


def _plc(*cards, rack_tag="RK-1", area="a1", system="PLC-1") -> PlcList:
    return PlcList(systems=[PlcSystem(tag=system, racks=[PlcRack(tag=rack_tag, plant_area_id=area, rack_type_id="rack", cards=[
        None if c is None else PlcCard(card_type_id=c) for c in cards])])])


def test_points_follow_the_card_type() -> None:
    plc, errors = normalise_points(_plc("net", "di16", None, "ai8"), CAT)
    assert errors == {}
    net, di, _, ai = plc.systems[0].racks[0].cards
    assert (len(net.points), len(di.points), len(ai.points)) == (0, 16, 8)
    assert [p.channel for p in ai.points] == list(range(8))
    # Points are kept by channel when the type changes; a tagged channel can't be dropped.
    di.points[3].tag, di.points[12].tag = "XS-3", "XS-12"
    di.card_type_id = "di8"
    out, errors = normalise_points(plc, CAT)
    card = out.systems[0].racks[0].cards[1]
    assert list(errors.values()) == ["RK-1-S2: channel(s) 12 have a tag or description, and the card type has 8 channel(s). "
                                     "Clear them first."]
    assert [p.channel for p in card.points][-2:] == [7, 12] and card.points[3].tag == "XS-3"


def test_checks() -> None:
    plc, _ = normalise_points(PlcList(systems=[
        PlcSystem(tag="PLC-1", racks=[
            PlcRack(tag="RK-1", rack_type_id="rack", cards=[PlcCard(card_type_id="di8", tag="CARD-A")]),
            PlcRack(tag="rk-1 ", plant_area_id="gone", rack_type_id="nope", cards=[PlcCard(card_type_id="zz", tag="card-a")])]),
        PlcSystem(tag="plc-1"), PlcSystem(tag=" ")]), CAT)
    plc.systems[0].racks[0].cards[0].points[0].tag = "XS-1"
    plc.systems[0].racks[0].cards[0].points[1].tag = "xs-1"
    errors, findings = check_plc(plc, CAT, {"a1"})
    s0, s1, s2 = plc.systems
    r0, r1 = s0.racks
    assert errors == {
        f"{s1.id}.tag": "System tag 'plc-1' is used twice", f"{s2.id}.tag": "System tag is required",
        f"{r1.id}.tag": "Rack tag 'rk-1' is used twice", f"{r1.id}.rack_type_id": "The rack type is not in the catalogue",
        f"{r1.id}.plant_area_id": "That plant area no longer exists",
        f"{r1.cards[0].id}.card_type_id": "The card type is not in the catalogue",
        f"{r1.cards[0].id}.tag": "Card name 'card-a' is used twice",
        f"{r0.cards[0].id}.points.1": "IO point tag 'xs-1' is used twice",
    }
    assert [(f.code, f.item) for f in findings] == [("P1", "RK-1"), ("P2", "RK-1")]


def test_old_register_shape() -> None:
    hw = as_hardware(_plc("net", "di16", None, "ai8"))
    assert [r.card for r in schedule(hw, CAT)] == ["RK-1-S1", "RK-1-S2", "RK-1-S4"]


def test_move_from_the_generators_registers() -> None:
    a = Hardware(panels=[Panel(tag="PCC-01", location="100", racks=[Rack(number=1, rack_type_id="rack", cards=[
        Card(card_type_id="net"), Card(card_type_id="di16", spare=True, notes="n")])])])
    b = Hardware(panels=[Panel(tag="pcc-01", racks=[Rack(number=1, rack_type_id="rack"), Rack(number=2, rack_type_id="rack",
                                                                                            cards=[Card(card_type_id="do8")])]),
                         Panel(tag="PCC-02", description="Second")])
    plc = from_registers([a, b], {"100": "a1"}, CAT)
    assert [(s.tag, s.description, [(r.tag, r.plant_area_id) for r in s.racks]) for s in plc.systems] == [
        ("PCC-01", "", [("PCC-01-R1", "a1"), ("PCC-01-R2", None)]), ("PCC-02", "Second", [])]
    di = plc.systems[0].racks[0].cards[1]
    assert (di.card_type_id, di.spare, di.notes, len(di.points)) == ("di16", True, "n", 16)


def test_workbook_round_trip() -> None:
    plc, _ = normalise_points(_plc("net", "di16", None, "ai8"), CAT)
    plc.systems[0].manufacturer, plc.systems[0].model = "ACME", "X-1"
    plc.systems[0].racks[0].cards[1].points[2].tag = "XS-102"
    plc.systems[0].racks[0].cards[1].points[2].description = "Pump running"
    cat = CAT.model_copy(deep=True)
    cat.card_types[3].part_number = "DI-16X"
    data = write_workbook(plc, cat, {"a1": "100"})
    res = read_workbook(data, CAT, {"100": "a1"})
    s = res.plc.systems[0]
    r = s.racks[0]
    assert (s.tag, s.manufacturer, s.model, r.tag, r.plant_area_id) == ("PLC-1", "ACME", "X-1", "RK-1", "a1")
    assert [None if c is None else c.card_type_id for c in r.cards] == ["net", "di16", None, "ai8"]
    p = r.cards[1].points[2]
    assert (p.tag, p.description) == ("XS-102", "Pump running")
    assert res.catalogue.card_types[3].part_number == "DI-16X" and res.notes == []
