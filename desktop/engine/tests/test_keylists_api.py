# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from workbench_desktop import storage
from workbench_desktop.app import app

client = TestClient(app)
URL = "/api/keylists/plant-areas"
ANN = {"X-Workbench-User": "ACME\\ann", "X-Workbench-Machine": "PC-01"}
BOB = {"X-Workbench-User": "ACME\\bob", "X-Workbench-Machine": "PC-02"}

NODES = [
    {"id": "b1", "parent_id": "a1", "wbs": "1.1", "tag": "B-10", "description": "Substation", "area_type": "Building"},
    {"id": "a1", "parent_id": None, "wbs": "1", "tag": "A-100", "description": "Process area", "area_type": "Area"},
    {"id": "r1", "parent_id": "b1", "tag": "R-101", "description": "Control room", "area_type": "Room"},
    {"id": "p1", "parent_id": "r1", "tag": "LCP-01", "description": "Local control panel", "area_type": "Panel"},
]


@pytest.fixture(autouse=True)
def data_dir(tmp_path: Path):
    storage.configure(tmp_path)
    yield tmp_path


def test_plant_areas_save_rules_and_persistence(data_dir: Path) -> None:
    # Every project has the list from the start, empty.
    assert client.get(URL).json() == {"nodes": [], "updated_at": None}
    ov = client.get("/api/keylists").json()
    assert ov == {"plant_areas": {"items": 0, "depth": 0}, "area_types": ["WBS", "Area", "Building", "Room", "Panel"]}

    saved = client.put(URL, json={"nodes": NODES})
    assert saved.status_code == 200, saved.text
    assert [n["id"] for n in saved.json()["nodes"]] == ["a1", "b1", "r1", "p1"]  # parents first
    assert saved.json()["nodes"][2]["wbs"] == ""

    # Tag and description: required, unique in the whole list. WBS: unique when filled.
    bad = client.put(URL, json={"nodes": NODES + [
        {"id": "x1", "parent_id": None, "wbs": "1.1", "tag": "a-100", "description": "CONTROL ROOM", "area_type": "WBS"},
        {"id": "x2", "parent_id": None, "tag": "", "description": " ", "area_type": "WBS"},
    ]})
    assert bad.status_code == 422
    assert set(bad.json()["fields"]) == {"x1.tag", "x1.description", "x1.wbs", "x2.tag", "x2.description"}
    # Only the listed area types.
    assert client.put(URL, json={"nodes": [{"tag": "S", "description": "Shed", "area_type": "Shed"}]}).status_code == 422
    assert client.put(URL, json={"nodes": [{"tag": "S", "description": "Shed"}]}).status_code == 422

    # Nothing of the refused saves was kept; the list survives a restart.
    storage.configure(data_dir)
    assert [n["tag"] for n in client.get(URL).json()["nodes"]] == ["A-100", "B-10", "R-101", "LCP-01"]
    assert client.get("/api/keylists").json()["plant_areas"] == {"items": 4, "depth": 4}
    assert client.get("/api/dashboard").json()["counts"]["plant_areas"] == 4


def test_plant_areas_change_log_and_conflicts() -> None:
    ann_tag = client.get(URL, headers=ANN).headers["ETag"]
    bob_tag = client.get(URL, headers=BOB).headers["ETag"]
    r = client.put(URL, json={"nodes": NODES}, headers={**ANN, "If-Match": ann_tag})
    assert r.status_code == 200
    # Bob still has the empty list: his save is refused, not written over Ann's.
    r = client.put(URL, json={"nodes": NODES[1:2]}, headers={**BOB, "If-Match": bob_tag})
    assert r.status_code == 409 and r.json()["changed_by"] == "ACME\\ann"
    assert len(client.get(URL).json()["nodes"]) == 4
    bob_tag = client.get(URL, headers=BOB).headers["ETag"]
    renamed = [dict(n, description="Main substation") if n["id"] == "b1" else n for n in NODES]
    assert client.put(URL, json={"nodes": renamed}, headers={**BOB, "If-Match": bob_tag}).status_code == 200

    log = client.get("/api/audit", params={"entity": "plant_areas", "record_id": "plant-areas"}).json()
    entries = log["entries"] if isinstance(log, dict) else log
    assert [e["user"] for e in entries] == ["ACME\\bob", "ACME\\ann"]
    assert all(e["label"] == "Plant Areas" for e in entries)
    assert any(c["new"] == "Main substation" for c in entries[0]["changes"])
