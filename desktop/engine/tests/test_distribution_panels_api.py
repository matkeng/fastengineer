# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from workbench_desktop import storage
from workbench_desktop.app import app

client = TestClient(app)
URL = "/api/distribution-panels"
ANN = {"X-Workbench-User": "ACME\\ann", "X-Workbench-Machine": "PC-01"}
BOB = {"X-Workbench-User": "ACME\\bob", "X-Workbench-Machine": "PC-02"}


@pytest.fixture(autouse=True)
def data_dir(tmp_path: Path):
    storage.configure(tmp_path)
    yield tmp_path


def _panel(**more) -> dict:
    return {"id": "p1", "load_ref": "eel/smcc1", "ways": 6} | more


def _loads() -> None:
    """The sample plant's Load List (MCC-1 and MCC-2 with their loads), and no panels yet."""
    client.post("/api/sample-data")
    for s in client.get("/api/deliverables").json()["deliverables"]:
        client.delete(f"/api/deliverables/{s['deliverable']['id']}")
    assert client.put(URL, json={"panels": []}).status_code == 200


def test_an_empty_project_has_no_panels() -> None:
    view = client.get(URL).json()
    assert view["doc"]["panels"] == [] and view["schedules"] == {} and view["load_panels"] == []
    assert view["kinds"]["spare_cb"] == "DP - Spare CB" and 32 in view["cb_ratings"]
    assert client.get("/api/keylists").json()["distribution_panels"] == {"items": 0}


def test_circuits_come_from_the_load_list() -> None:
    _loads()
    view = client.get(URL).json()
    assert [c["label"] for c in view["load_panels"]] == [
        "MCC-1 – Motor control centre 1", "MCC-2 – Motor control centre 2", "MSB-1 – Main switchboard"]
    draft = {"panels": [_panel()]}
    checked = client.post(f"{URL}/check", json=draft).json()
    waiting = checked["schedules"]["p1"]["unplaced"]
    assert len(waiting) >= 2 and all(u["poles"] == 3 for u in waiting) and checked["doc"]["panels"][0]["tag"] == "MCC-1"
    assert client.get(URL).json()["doc"]["panels"] == []  # a check saves nothing

    placed = client.post(f"{URL}/place", json={"doc": draft, "panel_id": "p1"}).json()
    entries = placed["doc"]["panels"][0]["entries"]
    assert [e["way"] for e in entries] == list(range(1, len(entries) + 1)) and placed["schedules"]["p1"]["unplaced"] == []
    entries[0]["rows"][0]["cb_rating"] = 32
    saved = client.put(URL, json=placed["doc"])
    assert saved.status_code == 200, saved.text
    s = saved.json()["schedules"]["p1"]
    assert (s["rows"][0]["circuit"], s["rows"][0]["cb_rating"], s["rows"][0]["span"], s["rows"][1]["span"]) == ("QR1", 32, 3, 0)
    assert s["totals"]["total_kw"] > 0 and s["totals"]["max_kva"] == 180 and len(s["rows"]) == 18
    assert client.get("/api/keylists").json()["distribution_panels"] == {"items": 1}

    # A load moved to another panel stays on the schedule, marked.
    tag = s["rows"][0]["tag"]
    row = next(r for r in client.get("/api/loadlist").json()["rows"] if r["values"].get("tag") == tag)
    moved = client.put("/api/loadlist/allocations", json={"rows": [{"recipe_id": row["recipe_id"], "key": row["key"]}],
                                                          "supplied_from": "eel/smcc2"})
    assert moved.status_code == 200, moved.text
    s = client.get(URL).json()["schedules"]["p1"]
    assert s["rows"][0]["problem"] == "Its load is no longer supplied from this panel" and "QR1" in " ".join(s["findings"])


def test_rules_conflicts_and_the_change_log() -> None:
    _loads()
    bad = client.put(URL, json={"panels": [_panel(ways=5, entries=[
        {"id": "e1", "way": 9, "pole": "R", "kind": "spare_cb", "rows": [{"cb_rating": 16}]}]), {"id": "p2", "tag": " "}]})
    assert bad.status_code == 422 and set(bad.json()["fields"]) == {"p1.ways", "e1.way", "p2.tag"}

    ann = client.get(URL, headers=ANN).headers["ETag"]
    bob = client.get(URL, headers=BOB).headers["ETag"]
    spare = {"id": "e1", "way": 1, "pole": "W", "kind": "spare_cb", "rows": [{"cb_rating": 16}]}
    ok = client.put(URL, json={"panels": [_panel(entries=[spare])]}, headers={**ANN, "If-Match": ann})
    assert ok.status_code == 200, ok.text
    row = ok.json()["schedules"]["p1"]["rows"][1]
    assert (row["circuit"], row["load_type"], row["cb_rating"], row["total_w"]) == ("QW1", "DP - Spare CB", 16, 0)
    stale = client.put(URL, json={"panels": []}, headers={**BOB, "If-Match": bob})
    assert stale.status_code == 409 and stale.json()["conflict"] is True
    log = client.get("/api/audit", params={"entity": "distribution_panels"}).json()
    assert log and "Distribution Panels" in str(log)


def test_a_panel_is_issued_as_a_deliverable(tmp_path: Path) -> None:
    _loads()
    api = "/api/deliverables"
    draft = client.post(f"{URL}/place", json={"doc": {"panels": [_panel()]}, "panel_id": "p1"}).json()["doc"]
    assert "Distribution Panel" in client.get(api).json()["types"]
    none = client.post(api, json={"type": "Distribution Panel", "name": "MCC-1 schedule", "panel_id": "p1"})
    assert none.status_code == 422 and none.json()["fields"] == {"panel_id": "Choose a distribution panel"}
    client.put(URL, json=draft)
    made = client.post(api, json={"type": "Distribution Panel", "name": "MCC-1 schedule", "doc_number": "E-DP-001", "panel_id": "p1"})
    assert made.status_code == 200, made.text
    d = made.json()
    assert (d["source"], d["panel_id"], d["generator_id"]) == ("panel", "p1", "")
    wrong = client.post(api, json={"type": "Load List", "name": "x", "source": "panel", "panel_id": "p1"})
    assert wrong.status_code == 422 and "source" in wrong.json()["fields"]
    ov = client.get(api).json()
    assert ov["panels"] == [{"id": "p1", "tag": "MCC-1", "title": ""}] and ov["project_columns"]["Distribution Panel"][0] == "Circuit"
    assert ov["deliverables"][0]["generator"] == "Distribution Panels: MCC-1"

    cur = client.get(f"{api}/{d['id']}", params={"rows": True}).json()["current"]
    assert (cur["source"], cur["problem"], cur["rows"], cur["next_letter"]) == ("panel", None, 18, "A")
    assert dict(cur["summary"])["Maximum kVA Rating"] == 180 and cur["result"]["rows"][0]["cells"][0] == "QR1"
    assert client.post(f"{api}/{d['id']}/revisions", json={}).json()["letter"] == "A"

    # A breaker is changed and the panel issued again: one changed row, found by its circuit.
    draft["panels"][0]["entries"][0]["rows"][0]["cb_rating"] = 40
    assert client.put(URL, json=draft).status_code == 200
    b = client.post(f"{api}/{d['id']}/revisions", json={"description": "Breaker resized"}).json()
    assert (b["letter"], b["added"], b["removed"], b["changed"]) == ("B", 0, 0, 1)
    rev = client.get(f"{api}/revisions/{b['id']}").json()
    assert rev["changes"]["entries"][0]["key"] == "QR1" and rev["changes"]["entries"][0]["cells"][0]["new"] == 40
    assert dict(rev["summary"])["Panel"] == "MCC-1"

    out = tmp_path / "panel.xlsx"
    assert client.post(f"{api}/revisions/{b['id']}/export", json={"format": "xlsx", "path": str(out)}).status_code == 200
    from openpyxl import load_workbook
    wb = load_workbook(out)
    assert wb.sheetnames == ["Schedule", "Panel"] and wb["Panel"]["A1"].value == "Panel" and wb["Panel"]["B1"].value == "MCC-1"
    assert wb["Schedule"]["A2"].value == "QR1" and wb["Schedule"].max_row == 19
    assert client.post(f"{api}/revisions/{b['id']}/export", json={"format": "csv"}).status_code == 200

    # A panel a deliverable issues can't be removed; one that is gone stops the issue.
    gone = client.put(URL, json={"panels": []})
    assert gone.status_code == 422 and "MCC-1 schedule" in gone.json()["fields"]["p1.delete"]
    empty = client.put(URL, json={"panels": [_panel(entries=[])]})
    assert empty.status_code == 200
    assert "no circuits yet" in client.get(f"{api}/{d['id']}").json()["current"]["problem"]
    assert client.post(f"{api}/{d['id']}/revisions", json={}).status_code == 422
