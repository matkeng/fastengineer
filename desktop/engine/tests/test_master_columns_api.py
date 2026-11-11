# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""The project's columns of the master lists: edit them, and the rows, deliverables and
workbooks that use them follow."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from workbench_desktop import storage
from workbench_desktop.app import app

client = TestClient(app)
API = "/api/master-columns"


@pytest.fixture(autouse=True)
def data_dir(tmp_path: Path):
    storage.configure(tmp_path)
    yield tmp_path


def _cols(key: str) -> list[str]:
    return next(x for x in client.get(API).json()["lists"] if x["key"] == key)["columns"]


def _edit(key: str, *, rename: dict[str, str] | None = None, drop: tuple[str, ...] = (), add: tuple[str, ...] = ()) -> list[dict]:
    rename = rename or {}
    return [{"name": rename.get(c, c), "was": c} for c in _cols(key) if c not in drop] + [{"name": a, "was": ""} for a in add]


def _put(lists: dict, dry_run: bool = False):
    return client.put(API, params={"dry_run": dry_run}, json={"lists": lists})


def test_the_built_in_columns_until_changed_and_what_is_refused() -> None:
    view = client.get(API).json()
    cable = view["lists"][0]
    assert cable["key"] == "cable_schedule" and cable["columns"] == cable["defaults"] and cable["columns"][0] == "Cable Number"
    assert cable["protected"] == ["Cable Number", "Cable Type", "Cores", "Cable Code"]
    assert view["extra"] == ["Generator", "Confirmed"] and "Repeat" in view["reserved"]

    def refused(lists: dict) -> dict:
        res = _put(lists)
        assert res.status_code == 422, res.text
        return res.json()["fields"]

    assert "can be moved but not renamed" in refused({"equipment_list": _edit("equipment_list", rename={"Tag": "Tag No"})})["equipment_list"]
    assert "can be moved but not renamed" in refused({"cable_schedule": _edit("cable_schedule", drop=("Cores",))})["cable_schedule"]
    assert "twice" in " ".join(refused({"equipment_list": _edit("equipment_list", add=("remarks",))}).values())
    assert "kept for" in " ".join(refused({"instrument_list": _edit("instrument_list", add=("Confirmed",))}).values())
    assert "needs a name" in " ".join(refused({"instrument_list": _edit("instrument_list", add=(" ",))}).values())
    assert "not a master list" in refused({"load_list": []})["load_list"]
    assert client.get(API).json() == view  # nothing was saved


def test_rename_add_delete_follow_in_rows_deliverables_and_masters() -> None:
    assert client.post("/api/sample-data").status_code == 200
    deliverables = client.get("/api/deliverables").json()["deliverables"]
    for s in deliverables:
        client.delete(f"/api/deliverables/{s['deliverable']['id']}")
    made = client.post("/api/deliverables", json={"type": "PLC I/O List", "name": "IO", "source": "project",
                                                  "columns": ["Tag", "Channel", "Rack"], "filter_column": "rack",
                                                  "filter_values": ["R1"]})
    assert made.status_code == 200, made.text
    io_list = made.json()
    rev = client.post(f"/api/deliverables/{io_list['id']}/revisions", json={})
    assert rev.status_code == 200, rev.text  # an issued revision keeps its header

    cable_rows = [r for t in client.get("/api/keylists/load-types").json()["items"] for r in t["rows"].get("cable_schedule", [])]
    with_route = sum(1 for r in cable_rows if r.get("Route"))
    lists = {"plc_io_list": _edit("plc_io_list", rename={"Rack": "PLC Rack", "Channel": "Ch"}),
             "equipment_list": _edit("equipment_list", rename={"Remarks": "Notes"}, add=("Weight (kg)",)),
             "cable_schedule": _edit("cable_schedule", drop=("Route",))}
    # move a column: Description first on the Equipment List
    eq = lists["equipment_list"]
    lists["equipment_list"] = [eq[1], eq[0], *eq[2:]]

    dry = _put(lists, dry_run=True)
    assert dry.status_code == 200, dry.text
    impact = {i["key"]: i for i in dry.json()["impact"]}
    assert dry.json()["saved"] is False and "Rack" in _cols("plc_io_list")  # nothing changed
    assert impact["plc_io_list"]["renames"] == {"Rack": "PLC Rack", "Channel": "Ch"} and impact["plc_io_list"]["deliverables"] == ["IO"]
    assert impact["equipment_list"]["added"] == ["Weight (kg)"] and impact["equipment_list"]["renames"] == {"Remarks": "Notes"}
    assert impact["cable_schedule"]["deletes"] == ["Route"] and impact["cable_schedule"]["cells_dropped"] == with_route

    saved = _put(lists)
    assert saved.status_code == 200 and saved.json()["saved"] is True, saved.text
    assert _cols("equipment_list")[:2] == ["Description", "Tag"] and _cols("equipment_list")[-2:] == ["Notes", "Weight (kg)"]
    assert "Route" not in _cols("cable_schedule")

    # the row editors' columns, the rows, the masters and the deliverable all follow
    meta = {x["key"]: x["columns"] for x in client.get("/api/keylists/load-types/lists").json()["lists"]}
    assert meta["plc_io_list"] == _cols("plc_io_list")
    pumps = next(t for t in client.get("/api/keylists/equipment-packages").json()["types"] if t["name"] == "Centrifugal pump")
    assert pumps["rows"]["plc_io_list"][0]["PLC Rack"] == "<<Rack>>" and "Rack" not in pumps["rows"]["plc_io_list"][0]
    assert not any("Route" in r for t in client.get("/api/keylists/load-types").json()["items"] for r in t["rows"].get("cable_schedule", []))
    master = client.get("/api/master/plc_io_list").json()["result"]
    assert master["header"] == _cols("plc_io_list") + ["Generator", "Confirmed"]
    channel = master["header"].index("Ch")
    assert any(r["cells"][channel] for r in master["rows"])  # the renamed column still has its cells
    summary = {m["key"]: m for m in client.get("/api/master").json()}
    assert summary["equipment_list"]["columns"][:2] == ["Description", "Tag"]
    d = client.get(f"/api/deliverables/{io_list['id']}", params={"rows": True}).json()
    assert d["deliverable"]["columns"] == ["Tag", "Ch", "PLC Rack"] and d["deliverable"]["filter_column"] == "PLC Rack"
    assert d["current"]["result"]["header"] == ["Tag", "Ch", "PLC Rack"]
    assert client.get("/api/deliverables").json()["project_columns"]["Equipment List"][-3:] == ["Weight (kg)", "Generator", "Confirmed"]
    revision = client.get(f"/api/deliverables/revisions/{rev.json()['id']}").json()
    assert revision["result"]["header"] == ["Tag", "Channel", "Rack"]  # frozen as issued

    # a new column takes text in template rows; a deleted one is refused
    types = client.get("/api/keylists/load-types").json()["items"]
    t = next(t for t in types if t["rows"].get("equipment_list"))
    t["rows"]["equipment_list"][0]["Weight (kg)"] = "120"
    assert client.put("/api/keylists/load-types", json={"items": types}).status_code == 200
    eq_master = client.get("/api/master/equipment_list").json()["result"]
    assert 120 in [r["cells"][eq_master["header"].index("Weight (kg)")] for r in eq_master["rows"]]
    t["rows"]["cable_schedule"] = [{"Cable Number": "X", "Route": "Tray"}]
    bad = client.put("/api/keylists/load-types", json={"items": types})
    assert bad.status_code == 422 and "Route" in " ".join(bad.json()["fields"].values())

    # deleting a filtered column clears the deliverable's filter
    assert _put({"plc_io_list": _edit("plc_io_list", drop=("PLC Rack",))}).status_code == 200
    d = client.get(f"/api/deliverables/{io_list['id']}").json()["deliverable"]
    assert d["columns"] == ["Tag", "Ch"] and d["filter_column"] == "" and d["filter_values"] == []


def test_workbooks_use_the_project_columns() -> None:
    assert client.post("/api/sample-data").status_code == 200
    assert _put({"plc_io_list": _edit("plc_io_list", rename={"Channel": "Ch"}, add=("Card",))}).status_code == 200
    data = client.post("/api/list-workbooks/equipment-packages/export", json={}).content
    wb = load_workbook(io.BytesIO(data))
    sheet = wb["PLC I-O List rows"]
    head = [c.value for c in sheet[1]]
    assert head[0] == "Equipment type" and "Ch" in head and "Card" in head and "Channel" not in head
    sheet.cell(row=2, column=head.index("Card") + 1, value="DI-16")
    buf = io.BytesIO()
    wb.save(buf)
    res = client.post("/api/list-workbooks/equipment-packages/import", params={"filename": "x.xlsx", "apply": True}, content=buf.getvalue())
    assert res.status_code == 200, res.text
    assert res.json()["applied"] is True
    pumps = next(t for t in client.get("/api/keylists/equipment-packages").json()["types"] if t["name"] == "Centrifugal pump")
    assert pumps["rows"]["plc_io_list"][0]["Card"] == "DI-16" and pumps["rows"]["plc_io_list"][0]["Ch"] == "<<#1>>"
