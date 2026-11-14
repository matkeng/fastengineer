# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from workbench_desktop import storage
from workbench_desktop.app import app

client = TestClient(app)
URL = "/api/cable-routing"
ANN = {"X-Workbench-User": "ACME\\ann", "X-Workbench-Machine": "PC-01"}
BOB = {"X-Workbench-User": "ACME\\bob", "X-Workbench-Machine": "PC-02"}


@pytest.fixture(autouse=True)
def data_dir(tmp_path: Path):
    storage.configure(tmp_path)
    yield tmp_path


def _sample() -> dict:
    client.post("/api/sample-data")
    return client.get(URL).json()


def _cable(view: dict, number: str) -> dict:
    return next(c for c in view["cables"] if c["number"] == number)


def _schedule() -> dict[str, dict]:
    result = client.get("/api/master/cable_schedule").json()["result"]
    return {r["cells"][0]: dict(zip(result["header"], r["cells"])) for r in result["rows"]}


def test_an_empty_project_has_an_empty_map_with_the_default_rules() -> None:
    view = client.get(URL).json()
    doc = view["doc"]
    assert doc["placements"] == doc["nodes"] == doc["segments"] == [] and view["cables"] == [] and view["equipment"] == []
    assert [s["name"] for s in doc["services"]] == ["HV", "LV Power", "Control", "Instrumentation", "Comms"]
    assert doc["services"][1]["widths_mm"] == [150, 300, 450, 600, 750, 900] and doc["allowance"]["apply_to_master"] is False
    assert client.get("/api/keylists").json()["cable_routing"] == {"items": 0}


def test_the_sample_plants_cables_are_routed() -> None:
    view = _sample()
    assert view["errors"] == {} and view["warnings"] == [] and view["unplaced"] == []
    assert len(view["doc"]["nodes"]) == 7 and len(view["doc"]["segments"]) == 20
    assert {e["tag"] for e in view["equipment"]} >= {"MSB-1", "MCC-1", "P-101"} and all(e["placed"] for e in view["equipment"])
    assert {c["status"] for c in view["cables"]} == {"ok"}
    feeder, pump, fan = _cable(view, "MCC-1-P1"), _cable(view, "P-101-P1"), _cable(view, "F-301-P1")
    assert (feeder["route"], feeder["route_m"]) == ("N001-N002", 12)  # 3 + 6 + 3
    assert (pump["route"], pump["route_m"]) == ("N002-N004", 51)  # 3 + 40 + 8
    assert (fan["route"], fan["route_m"]) == ("N003-N007-N006", 97)  # the short way round the loop: 3 + 45 + 35 + 14
    assert feeder["od_mm"] == 62.6 and feeder["mass_kg_per_m"] == 11.04 and feeder["service_id"] == "lv"
    supply = next(s for s in view["segments"] if s["tag"] == "S-001")  # Primary Supply - MSB-1: 8 single cores and an earth
    lv = supply["services"][0]
    assert lv["cables"] == 9 and lv["trefoils"] == 2 and lv["width_mm"] in (300, 450) and lv["kg_per_m"] > 20


def test_a_draft_is_checked_without_saving_and_a_bad_one_is_refused() -> None:
    doc = _sample()["doc"]
    fan_route = {"via": [next(n["id"] for n in doc["nodes"] if n["tag"] == "N004")], "avoid": []}
    draft = doc | {"overrides": {"F-301-P1": fan_route}}
    checked = client.post(f"{URL}/check", json=draft).json()
    fan = _cable(checked, "F-301-P1")
    assert fan["route"] == "N003-N002-N004-N005-N006" and fan["overridden"] and fan["route_m"] == 3 + 6 + 40 + 35 + 20 + 14
    assert client.get(URL).json()["doc"]["overrides"] == {}  # a check saves nothing

    draft["segments"][4]["length_m"] = None
    draft["segments"][5]["tag"] = draft["segments"][6]["tag"]
    refused = client.put(URL, json=draft)
    assert refused.status_code == 422 and "is there twice" in refused.json()["detail"]
    assert client.post(f"{URL}/check", json=draft).json()["warnings"][0].startswith("1 segment(s) have no length yet: S-005")

    draft["segments"][5]["tag"] = "S-006"
    saved = client.put(URL, json=draft)
    assert saved.status_code == 200, saved.text
    assert "missing lengths" in {c["status"] for c in saved.json()["cables"]}
    again = client.post(f"{URL}/renumber", json=saved.json()["doc"] | {"nodes": saved.json()["doc"]["nodes"][::-1]}).json()
    assert [n["tag"] for n in again["doc"]["nodes"]] == [f"N00{i}" for i in range(1, 8)]


def test_routed_lengths_go_to_the_master_cable_schedule_when_switched_on() -> None:
    doc = _sample()["doc"]
    before = _schedule()
    assert before["P-101-P1"]["Length (m)"] != 55 and before["MSB-1-P1"]["Route"] == "L1"
    doc["allowance"] = {"apply_to_master": True, "tail_from_m": 2, "tail_to_m": 1.5, "contingency_pct": 0, "round_up_to_m": 1,
                        "route_column": "when blank"}
    view = client.put(URL, json=doc).json()
    assert _cable(view, "P-101-P1")["length_m"] == 55  # 51 + 3.5, rounded up
    after = _schedule()
    assert after["P-101-P1"]["Length (m)"] == 55 and after["P-101-P1"]["Route"] == "N002-N004"
    assert after["MSB-1-P1"]["Length (m)"] == 29 and after["MSB-1-P1"]["Route"] == "L1"  # a Route that is filled in is kept
    control = next(k for k in after if k.endswith("-C1"))
    assert after[control]["Length (m)"] == _cable(view, control)["length_m"]  # control cables too
    # a cable whose equipment is taken off the map keeps the length it had
    doc["placements"] = [p for p in doc["placements"] if p["tag"] != "P-101"]
    doc["segments"] = [s for s in doc["segments"] if s["a"]["id"] in {p["id"] for p in doc["placements"]} or s["a"]["kind"] == "node"]
    assert client.put(URL, json=doc).status_code == 200
    assert _schedule()["P-101-P1"]["Length (m)"] == before["P-101-P1"]["Length (m)"]


def test_placed_equipment_follows_its_tag() -> None:
    doc = _sample()["doc"]
    pump = next(p for p in doc["placements"] if p["tag"] == "P-101")
    pump["tag"], pump["description"] = "OLD-TAG", ""
    view = client.post(f"{URL}/check", json=doc).json()
    assert next(p for p in view["doc"]["placements"] if p["id"] == pump["id"])["tag"] == "P-101"
    doc["placements"].append({"id": "jb", "tag": " JB-1 ", "x": 0, "y": 0})  # typed in: not in the equipment list
    view = client.post(f"{URL}/check", json=doc).json()
    assert view["doc"]["placements"][-1]["tag"] == "JB-1" and view["errors"] == {}


def test_saves_are_logged_and_a_stale_save_is_refused() -> None:
    doc = _sample()["doc"]
    etag = client.get(URL, headers=ANN).headers["etag"]
    doc["segments"][0]["length_m"] = 30
    assert client.put(URL, json=doc, headers=ANN | {"If-Match": etag}).status_code == 200
    stale = client.put(URL, json=doc, headers=BOB | {"If-Match": etag})
    assert stale.status_code == 409 and stale.json()["changed_by"].endswith("ann")
    log = client.get("/api/audit", params={"entity": "cable_routing"}).json()
    assert log and "cable routing" in str(log).lower()


def test_the_tables_export() -> None:
    _sample()
    for table in ("cables", "segments"):
        for fmt in ("xlsx", "csv"):
            res = client.post(f"{URL}/export", json={"table": table, "format": fmt})
            assert res.status_code == 200 and len(res.content) > 200, res.text
    text = client.post(f"{URL}/export", json={"table": "segments", "format": "csv"}).content.decode("utf-8-sig")
    assert text.splitlines()[0].startswith("Segment,Length (m),Service,Cables") and "S-001,25,LV Power,9,2" in text
