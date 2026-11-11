# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from workbench_desktop import storage
from workbench_desktop.app import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def data_dir(tmp_path: Path):
    storage.configure(tmp_path)
    yield tmp_path


def test_sample_data_fills_an_empty_project_and_every_deliverable_can_be_issued():
    res = client.post("/api/sample-data")
    assert res.status_code == 200, res.text
    added = res.json()["added"]
    assert set(added) == {"Plant Areas", "Equipment Packages", "Equipment Codes", "Instrument Codes", "Load Types",
                          "Electrical Equipment List", "PLC List", "List import (MEL)", "Lists & tables", "Deliverables",
                          "Cable details (Load List)"}
    assert res.json()["skipped"] == []

    loads = client.get("/api/loadlist").json()["rows"]
    assert len(loads) == 12  # 9 from the MEL and 3 panels from the EEL
    assert all(r["load_type_id"] and r["plant_area_id"] and r["supplied_from"] for r in loads)

    overview = client.get("/api/deliverables").json()
    assert sorted(s["deliverable"]["type"] for s in overview["deliverables"]) == sorted(overview["types"])
    for s in overview["deliverables"]:
        d = s["deliverable"]
        assert s["generator"] == "Project Load List" and d["source"] == "project"
        cur = client.get(f"/api/deliverables/{d['id']}", params={"rows": True}).json()["current"]
        assert cur["problem"] is None and cur["rows"] and cur["warnings"] == [], (d["name"], cur["problem"], cur["warnings"])
        res = client.post(f"/api/deliverables/{d['id']}/revisions", json={"description": "First issue"})
        assert res.status_code == 200, res.text
        assert res.json()["letter"] == "A"


def test_sample_data_runs_once_and_leaves_existing_lists_alone():
    client.post("/api/sample-data")
    again = client.post("/api/sample-data").json()
    assert again["added"] == {} and len(again["skipped"]) == 10


def test_sample_data_does_not_touch_a_list_that_has_data(data_dir):
    client.put("/api/keylists/plant-areas", json={"nodes": [{"id": "x", "tag": "MINE", "description": "My area", "area_type": "Area"}]})
    res = client.post("/api/sample-data").json()
    assert "Plant Areas" in res["skipped"] and "Plant Areas" not in res["added"]
    assert [n["tag"] for n in client.get("/api/keylists/plant-areas").json()["nodes"]] == ["MINE"]
