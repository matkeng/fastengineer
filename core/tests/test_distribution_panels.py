# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
import pytest

from workbench_core.keylists import LoadListRow, LoadType
from workbench_core.keylists.distribution_panels import (PANEL_COLUMNS, SPARE_SPACE, DistributionPanel, DistributionPanelList,
                                                         PanelDivider, PanelEntry, PoleValues, auto_place, check_panels,
                                                         flatten, resolve, summary_lines)

TYPES = {"lt": LoadType(id="lt", code="LGT", name="Light - Walkway", rating_unit="kW", voltage=240, phases="AC-1-phase-LN"),
         "so": LoadType(id="so", code="SO3", name="Socket Outlet 3ph - 32A", rating_unit="Amps", voltage=415, phases="AC-3-phase")}


def _load(key: str, rating, load_type="lt", **more) -> LoadListRow:
    base = dict(recipe_id="m", key=key, source="MEL", target="MEL", values={"tag": key, "desc": f"{key} circuit",
                "load_rating": rating}, load_type_id=load_type, supplied_from="m/DP-1")
    return LoadListRow(**(base | more))


DP = LoadListRow(recipe_id="m", key="DP-1", source="MEL", target="MEL", values={"tag": "DP-1", "desc": "Field panel"},
                 is_panel=True, supplied_from="primary")
LOADS = {r.ref(): r for r in (DP, _load("L-1", 0.06), _load("L-2", 0.12), _load("S-1", 20, "so"),
                              _load("X-9", 1, supplied_from="m/OTHER"), _load("L-0", 1, status="deleted"))}


def _panel(**more) -> DistributionPanel:
    return DistributionPanel(**(dict(id="p1", load_ref="m/DP-1", tag="DP-1", ways=4) | more))


def test_auto_place_and_resolve() -> None:
    p = auto_place(_panel(), LOADS, TYPES)
    assert [(e.load_ref, e.way, e.pole, e.poles) for e in p.entries] == [
        ("m/L-1", 1, "R", 1), ("m/L-2", 1, "W", 1), ("m/S-1", 2, "R", 3)]
    p.entries[0].rows[0] = PoleValues(cb_rating=16, qty=12, watts_each=5)
    p.entries.append(PanelEntry(id="sp", way=3, pole="B", kind="spare_cb", rows=[PoleValues(cb_rating=16)]))
    p.dividers.append(PanelDivider(before_way=3, label="Lighting Contactor"))
    s = resolve(p, LOADS, TYPES)
    assert [r.circuit for r in s.rows] == ["QR1", "QW1", "QB1", "QR2", "QW2", "QB2", "QR3", "QW3", "QB3", "QR4", "QW4", "QB4"]
    r1, w1, b1, r2, w2 = s.rows[:5]
    assert (r1.tag, r1.description, r1.load_type, r1.qty, r1.watts_each, r1.total_w, r1.cb_rating, r1.side) == (
        "L-1", "L-1 circuit", "Light - Walkway", 12, 5, 60, 16, "Left")
    assert (w1.qty, w1.watts_each, w1.qty_default, w1.watts_default, w1.total_w) == (1, 120, True, True, 120)
    assert (b1.kind, b1.load_type, b1.entry_id, b1.span) == ("space", SPARE_SPACE, None, 1)
    # the three-pole socket: one entry over three rows, its amps on each pole
    assert (r2.span, w2.span, r2.side, w2.entry_id) == (3, 0, "Right", r2.entry_id)
    assert r2.watts_each == pytest.approx(20 * 240 * 0.85) and r2.load_type == "Socket Outlet 3ph - 32A"
    spare = s.rows[8]
    assert (spare.circuit, spare.load_type, spare.cb_rating, spare.total_w, spare.qty) == ("QB3", "DP - Spare CB", 16, 0, None)
    assert [r.section for r in s.rows] == [""] * 6 + ["Lighting Contactor"] * 6
    assert s.totals.phase_w == pytest.approx([60 + 4080, 120 + 4080, 4080])
    assert (s.title, s.unplaced, s.findings) == ("Field panel", [], [])


def test_findings() -> None:
    p = _panel(entries=[PanelEntry(way=1, pole="R", load_ref="m/X-9", rows=[PoleValues()]),
                        PanelEntry(way=1, pole="W", load_ref="m/GONE", rows=[PoleValues(cb_rating=400)])],
               isolator_rating=100, upstream_cb=250)
    s = resolve(p, LOADS, TYPES)
    assert s.rows[0].problem == "Its load is no longer supplied from this panel"
    assert s.rows[1].problem == "Its load is no longer in the Load List"
    assert [u.tag for u in s.unplaced] == ["L-1", "L-2", "S-1"] and s.unplaced[2].poles == 3
    text = " ".join(s.findings)
    assert "3 load(s) supplied from this panel" in text and "QW1" in text and "upstream CB" in text
    assert resolve(_panel(load_ref=None, tag="DP-9"), LOADS, TYPES).findings[0].startswith("Not linked")


def test_single_phase() -> None:
    p = auto_place(_panel(phase_type="single-phase", ways=2), LOADS, TYPES)
    assert [(e.way, e.pole, e.poles) for e in p.entries] == [(1, None, 1), (2, None, 1)]  # the third doesn't fit
    s = resolve(p, LOADS, TYPES)
    assert [r.circuit for r in s.rows] == ["Q1", "Q2"] and s.totals.phases == [""]
    assert [u.tag for u in s.unplaced] == ["S-1"]


def test_checks() -> None:
    ok, errors = check_panels(DistributionPanelList(panels=[_panel(tag="old name", title="  T  ")]), LOADS)
    assert errors == {} and (ok.panels[0].tag, ok.panels[0].title) == ("DP-1", "T")
    bad = _panel(ways=5, voltage=0, power_factor=1.5, isolator_rating=0, upstream_cb=0, entries=[
        PanelEntry(id="a", way=9, pole="R", load_ref="m/L-1", rows=[PoleValues()]),
        PanelEntry(id="b", way=1, pole=None, load_ref="m/L-1", rows=[PoleValues()]),
        PanelEntry(id="c", way=2, pole="W", poles=3, load_ref="m/S-1", rows=[PoleValues()]),
        PanelEntry(id="d", way=2, pole="B", kind="spare_cb", rows=[PoleValues(qty=-1)]),
        PanelEntry(id="e", way=3, pole="R", rows=[PoleValues()])],
        dividers=[PanelDivider(id="x", before_way=2, label=" "), PanelDivider(id="y", before_way=1, label="A"),
                  PanelDivider(id="z", before_way=1, label="B")])
    other = DistributionPanel(id="p2", load_ref="m/DP-1", tag="DP-1")
    unlinked = DistributionPanel(id="p3", tag=" ")
    _, errors = check_panels(DistributionPanelList(panels=[bad, other, unlinked]), LOADS)
    assert set(errors) == {"p1.ways", "p1.voltage", "p1.power_factor", "p1.isolator_rating", "p1.upstream_cb", "a.way",
                           "b.pole", "b.load_ref", "c.pole", "c.rows", "d.rows", "d.way", "e.load_ref", "x.label",
                           "x.before_way", "z.before_way", "p2.load_ref", "p2.tag", "p3.tag"}
    single = _panel(phase_type="single-phase", entries=[PanelEntry(id="a", way=1, pole="R", poles=3, rows=[PoleValues()] * 3)])
    assert set(check_panels(DistributionPanelList(panels=[single]), LOADS)[1]) == {"a.pole", "a.poles", "a.load_ref"}


def test_flatten_and_summary() -> None:
    p = auto_place(_panel(), LOADS, TYPES)
    p.dividers.append(PanelDivider(before_way=3, label="Lighting Contactor"))
    s = resolve(p, LOADS, TYPES)
    r = flatten(s)
    assert r.header == list(PANEL_COLUMNS) and len(r.rows) == 12 and all(x.run_row_id for x in r.rows)
    assert r.rows[1].cells == ["QW1", 1, "White", "Left", "", "L-2", "L-2 circuit", "Light - Walkway", 1, 120, 120, ""]
    assert r.rows[4].cells[5:8] == ["S-1", "S-1 circuit", "Socket Outlet 3ph - 32A"]  # every row of a three-pole circuit
    assert r.rows[2].cells == ["QB1", 1, "Blue", "Left", "", "", "", SPARE_SPACE, "", "", "", ""]
    assert r.rows[6].cells[4] == "Lighting Contactor" and r.rows[0].run_row_id == "p1:QR1"
    lines = dict(summary_lines(p, s))
    assert (lines["Panel"], lines["Phase type"], lines["Maximum kVA Rating"], lines["Single Phase Voltage"]) == (
        "DP-1", "Three-phase", 180, 240)
    assert lines["kVA White"] == pytest.approx((120 + 4080) / 0.85 / 1000, abs=0.01) and "3PH kW" in lines
