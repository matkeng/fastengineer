# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
from __future__ import annotations

import pytest

from workbench_core.generators.models import BuildResult, BuildStats, OutputRow
from workbench_core.keylists.cable_routing import (MAX_NODES, TREFOIL_FACTOR, Allowance, CableOverride, CableRouting, End, LadderOverride,
                                                   Placement, RouteNode, add_node, add_segment, apply_routes, check_routing, compute,
                                                   final_length, renumber)
from workbench_core.keylists.cable_types import CableType

HEADER = ["Cable Number", "From", "To", "Cable Type", "Cable Code", "Cores", "Size", "Length (m)", "Route"]
TYPES = [CableType(id="p", code="P16", type="Power", cores="4C+E", diameter="16", overall_diameter_mm=20, mass_kg_per_m=1.5),
         CableType(id="s", code="S300", type="Power", cores="1C", diameter="300", overall_diameter_mm=30, mass_kg_per_m=3),
         CableType(id="c", code="C1.5", type="Control", cores="5C+E", diameter="1.5", overall_diameter_mm=12),
         CableType(id="x", code="X", type="Power", cores="2C+E", diameter="4")]


def schedule(*rows: list) -> BuildResult:
    return BuildResult(header=HEADER, rows=[OutputRow(cells=[*r, *[""] * (len(HEADER) - len(r))]) for r in rows], stats=BuildStats())


def node(e: str) -> End:
    return End(kind="node", id=e)


def equipment(e: str) -> End:
    return End(kind="equipment", id=e)


def loop() -> CableRouting:
    """MCC - N001, then two ways round to N003 (via N002: 10 + 10; via N004: 5 + 30), N003 - P1; N002 - P2.
          N002
         /    \\
    MCC-N001  N003-P1
         \\    /
          N004
    """
    doc = CableRouting(placements=[Placement(id="mcc", tag="MCC-1"), Placement(id="p1", tag="P-1"), Placement(id="p2", tag="P-2")])
    for i in range(4):
        add_node(doc, 100 * i, 0).id = f"n{i + 1}"
    for a, b, length in ((equipment("mcc"), node("n1"), 2), (node("n1"), node("n2"), 10), (node("n2"), node("n3"), 10),
                         (node("n1"), node("n4"), 5), (node("n4"), node("n3"), 30), (node("n3"), equipment("p1"), 3),
                         (node("n2"), equipment("p2"), 4)):
        seg = add_segment(doc, a, b, length)
        seg.id = f"s{len(doc.segments)}"
    return doc


def tags(doc: CableRouting, ids: list[str]) -> list[str]:
    by_id = {s.id: s.tag for s in doc.segments}
    return [by_id[i] for i in ids]


def test_tags_are_given_in_order_and_not_reused() -> None:
    doc = loop()
    assert [n.tag for n in doc.nodes] == ["N001", "N002", "N003", "N004"] and doc.segments[-1].tag == "S-007"
    doc.nodes.pop()  # N004 goes
    assert add_node(doc, 0, 0).tag == "N005"
    doc.next_node = 1000  # the numbers ran out: the lowest free one
    assert add_node(doc, 0, 0).tag == "N004"
    full = CableRouting(nodes=[RouteNode(id=str(i), tag=f"N{i:03d}") for i in range(1, MAX_NODES + 1)])
    with pytest.raises(ValueError, match="999"):
        add_node(full, 0, 0)
    full.nodes.append(RouteNode(id="more", tag="N999"))
    assert "nodes" in check_routing(full)[1]
    again = renumber(doc)
    assert [n.tag for n in again.nodes] == ["N001", "N002", "N003", "N004", "N005"] and again.next_node == 6


def test_a_map_is_checked() -> None:
    doc = loop()
    assert check_routing(doc)[1:] == ({}, [])
    doc.segments[1].length_m = None
    doc.segments[2].tag = "S-001"
    doc.segments[3].b = node("gone")
    doc.segments[4].b = doc.segments[4].a
    doc.segments[5].length_m = -1
    doc.nodes[0].tag = "node 1"
    doc.overrides = {"C1": CableOverride(via=["n2", "gone"]), "C2": CableOverride()}
    checked, errors, warnings = check_routing(doc)
    assert errors == {"s3.tag": "Segment S-001 is there twice", "s4.b": "S-004 ends on something that is no longer on the map",
                      "s5.b": "S-005 starts and ends on the same thing", "s6.length_m": "Length is 0 or more",
                      "n1.tag": "A node's tag is N001 to N999"}
    assert "1 segment(s) have no length yet: S-002." in warnings and any("C1" in w for w in warnings)
    assert checked.overrides == {"c1": CableOverride(via=["n2"])}
    assert checked.next_node == 5 and checked.next_segment == 8


def test_the_shortest_way_round_a_loop() -> None:
    doc = loop()
    done = compute(doc, schedule(["C1", "MCC-1", "P-1", "Power", "P16"], ["C2", "mcc-1", "P-2"], ["C3", "P-1", "P-2"],
                                 ["C4", "MCC-1", "MCC-1"], ["C5", "MCC-1", "T-9"], ["C6", "Primary Supply", "P-1"]), TYPES)
    c1, c2, c3, c4, c5, c6 = done.cables
    assert tags(doc, c1.segments) == ["S-001", "S-002", "S-003", "S-006"] and c1.route_m == 25 and c1.length_m == 25
    assert c1.nodes == ["N001", "N002", "N003"] and c1.route == "N001-N002-N003" and c1.status == "ok"
    assert c2.route_m == 16 and c3.route_m == 17 and c3.route == "N003-N002"
    assert [c.status for c in (c4, c5, c6)] == ["same equipment", "to not placed", "from not placed"]
    assert (c1.od_mm, c1.mass_kg_per_m, c1.service_id) == (20, 1.5, "lv") and c2.od_mm is None


def test_equipment_is_not_a_way_through() -> None:
    doc = CableRouting(placements=[Placement(id=i, tag=i.upper()) for i in ("a", "b", "c")])
    add_segment(doc, equipment("a"), equipment("b"), 5)
    add_segment(doc, equipment("b"), equipment("c"), 5)
    c1, c2 = compute(doc, schedule(["C1", "A", "C"], ["C2", "A", "B"]), TYPES).cables
    assert c1.status == "no route" and c2.status == "ok" and c2.route == "S-001" and c2.route_m == 5


def test_two_ladders_between_the_same_nodes() -> None:
    doc = CableRouting(placements=[Placement(id="a", tag="A"), Placement(id="b", tag="B")])
    add_segment(doc, equipment("a"), equipment("b"), 9)
    short = add_segment(doc, equipment("a"), equipment("b"), 7)
    assert compute(doc, schedule(["C1", "A", "B"]), TYPES).cables[0].segments == [short.id]


def test_a_segment_with_no_length_is_the_last_resort() -> None:
    doc = loop()
    doc.segments[4].length_m = None  # N004 - N003: the long way round stays the long way
    assert compute(doc, schedule(["C1", "MCC-1", "P-1"]), TYPES).cables[0].route_m == 25
    doc.segments[5].length_m = None  # N003 - P-1: no measured way left
    c = compute(doc, schedule(["C1", "MCC-1", "P-1"]), TYPES).cables[0]
    assert c.status == "missing lengths" and c.route_m is None and c.length_m is None and c.segments[-1] == "s6"
    doc.segments = doc.segments[:5]
    assert compute(doc, schedule(["C1", "MCC-1", "P-1"]), TYPES).cables[0].status == "no route"


def test_a_cables_own_route() -> None:
    doc = loop()
    doc.overrides = {"c1": CableOverride(via=["n4"]), "c2": CableOverride(avoid=["s2"]), "c3": CableOverride(via=["s5"])}
    c1, c2, c3 = compute(doc, schedule(["C1", "MCC-1", "P-1"], ["C2", "MCC-1", "P-1"], ["C3", "MCC-1", "P-2"]), TYPES).cables
    assert c1.route == "N001-N004-N003" and c1.route_m == 40 and c1.overridden
    assert c2.route == "N001-N004-N003" and c2.route_m == 40
    assert c3.route == "N001-N004-N003-N002" and c3.route_m == 2 + 5 + 30 + 10 + 4
    doc.overrides = {"c1": CableOverride(avoid=["s1"])}
    assert compute(doc, schedule(["C1", "MCC-1", "P-1"]), TYPES).cables[0].status == "no route"


def test_the_allowance() -> None:
    assert final_length(25, Allowance()) == 25
    assert final_length(25.2, Allowance()) == 26
    assert final_length(25, Allowance(tail_from_m=3, tail_to_m=2, contingency_pct=10)) == 33  # 30 * 1.1
    assert final_length(25, Allowance(tail_from_m=1.5, contingency_pct=10, round_up_to_m=5)) == 30  # 29.15
    assert final_length(25.04, Allowance(round_up_to_m=0)) == 25.0


def test_lengths_go_into_the_cable_schedule() -> None:
    doc = loop()
    sched = schedule(["C1", "MCC-1", "P-1", "", "", "", "", 99, ""], ["C2", "MCC-1", "T-9", "", "", "", "", 50, ""],
                     ["C3", "MCC-1", "P-2", "", "", "", "", 1, "L1"])
    doc.allowance = Allowance(tail_from_m=1.5)
    out, warnings = apply_routes(sched, compute(doc, sched, TYPES).cables, doc.allowance)
    assert [r.cells[7:] for r in out.rows] == [[27, "N001-N002-N003"], [50, ""], [18, "L1"]] and not warnings
    assert sched.rows[0].cells[7] == 99  # the schedule given is not changed
    always = apply_routes(sched, compute(doc, sched, TYPES).cables, Allowance(route_column="always"))[0]
    assert always.rows[2].cells[8] == "N001-N002" and always.rows[0].cells[7] == 27
    never = apply_routes(sched, compute(doc, sched, TYPES).cables, Allowance(route_column="never"))[0]
    assert never.rows[0].cells[8] == ""
    bare = BuildResult(header=HEADER[:7], rows=[OutputRow(cells=["C1", "MCC-1", "P-1", "", "", "", ""])], stats=BuildStats())
    assert "no Length (m) column" in apply_routes(bare, compute(doc, bare, TYPES).cables, doc.allowance)[1][0]
    assert "no From column" in compute(doc, BuildResult(header=["Cable Number", "To"], rows=[], stats=BuildStats()), TYPES).warnings[0]


def test_ladders_by_service() -> None:
    doc = loop()
    rows = [[f"P{i}", "MCC-1", "P-1", "Power", "P16"] for i in range(1, 11)]  # 10 x 20 mm, 1.5 kg/m
    rows += [[f"C{i}", "MCC-1", "P-1", "Control", "C1.5"] for i in range(1, 4)]  # 3 x 12 mm, no mass
    rows += [["X1", "MCC-1", "P-1", "Power", "X"], ["Q1", "MCC-1", "P-2", "Power", "P16"]]
    done = compute(doc, schedule(*rows), TYPES)
    s1, s2, s3, s4, s5, s6, s7 = done.segments
    lv, control = s1.services
    assert (lv.service_id, lv.cables, lv.sum_od_mm, lv.required_mm, lv.width_mm, lv.ladders) == ("lv", 12, 220, 275, 300, 1)
    assert lv.fill_pct == 73.3 and lv.kg_per_m == 16.5 and lv.max_kg_per_m == 50
    assert lv.missing_od == lv.missing_mass == ["X1"] and lv.flags == ["1 cable(s) with no diameter", "1 cable(s) with no mass"]
    # control: two layers, 36 / 2 * 1.25
    assert (control.cables, control.sum_od_mm, control.required_mm, control.width_mm) == (3, 36, 22.5, 150)
    assert control.missing_mass == ["C1", "C2", "C3"] and control.kg_per_m == 0
    assert (s1.width_mm, s1.kg_per_m, s1.worst, len(s1.cables)) == (450, 16.5, "ok", 15)
    assert (s3.services[0].cables, s7.services[0].cables) == (11, 1)
    assert s4.services == s5.services == [] and s4.worst == "" and s4.width_mm == 0


def test_ladder_rules_and_what_is_installed() -> None:
    doc = loop()
    lv = doc.services[1]
    lv.spacing_factor, lv.max_kg_per_m, lv.widths_mm = 1, 10, [150, 300]
    rows = [[f"P{i}", "MCC-1", "P-1", "Power", "P16"] for i in range(1, 11)]
    load = compute(doc, schedule(*rows), TYPES).segments[0].services[0]
    # 10 x 20 mm with a diameter between: 400 mm, 500 with the spare: two 300 mm ladders
    assert (load.required_mm, load.width_mm, load.ladders, load.fill_pct, load.max_kg_per_m) == (500, 300, 2, 66.7, 20)
    assert load.flags == ["2 ladders of 300 mm"] and load.kg_per_m == 15
    doc.segments[0].ladders = {"lv": LadderOverride(width_mm=450, max_kg_per_m=12), "gone": LadderOverride(width_mm=1)}
    doc = check_routing(doc)[0]
    assert list(doc.segments[0].ladders) == ["lv"]
    seg = compute(doc, schedule(*rows), TYPES).segments[0]
    assert seg.services[0].flags == ["less than the spare left", "overloaded"] and seg.worst == "over"
    doc.segments[0].ladders["lv"].width_mm = 300
    assert "ladder too narrow" in compute(doc, schedule(*rows), TYPES).segments[0].services[0].flags


def test_single_cores_lie_in_trefoil() -> None:
    doc = loop()
    rows = [[f"S{i}", "MCC-1", "P-1", "Power", "S300", "1C"] for i in range(1, 8)]  # 7 single cores: two trefoils and one
    rows.append(["T1", "MCC-1", "P-2", "Power", "S300"])  # another circuit: on its own
    load = compute(doc, schedule(*rows), TYPES).segments[0].services[0]
    assert load.trefoils == 2 and load.cables == 8
    assert load.sum_od_mm == round(2 * 30 * TREFOIL_FACTOR + 30 + 30, 1) and load.kg_per_m == 24


def test_services_follow_the_rules() -> None:
    doc = loop()
    kinds = [CableType(code="A", type="Instrument"), CableType(code="B", type="Control", description="Instrolex Pairs"),
             CableType(code="C", application="Network", type="Fibre"), CableType(code="D", type="Power", voltage="6.35/11kV"),
             CableType(code="E", type="Power", voltage="0.6/1kV")]
    rows = [[f"K{i}", "MCC-1", "P-1", "", k.code] for i, k in enumerate(kinds)] + [["K9", "MCC-1", "P-1", "Instrument cable", ""]]
    assert [c.service_id for c in compute(doc, schedule(*rows), kinds).cables] == ["instrument", "instrument", "comms", "hv", "lv",
                                                                                 "instrument"]
    doc.services = doc.services[:2]
    checked, errors, _ = check_routing(doc)
    assert sorted(errors.values()) == ["That service no longer exists"] * 6


def test_a_ladder_of_cables_with_no_diameter_has_no_width() -> None:
    load = compute(loop(), schedule(["X1", "MCC-1", "P-1", "Power", "X"]), TYPES).segments[0].services[0]
    assert (load.width_mm, load.fill_pct, load.required_mm, load.missing_od) == (None, None, 0, ["X1"])
