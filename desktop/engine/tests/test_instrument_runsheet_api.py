# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from workbench_desktop import storage
from workbench_desktop.app import app

client = TestClient(app)
URL = "/api/instrument-runsheet"
ANN = {"X-Workbench-User": "ACME\\ann", "X-Workbench-Machine": "PC-01"}
BOB = {"X-Workbench-User": "ACME\\bob", "X-Workbench-Machine": "PC-02"}


@pytest.fixture(autouse=True)
def data_dir(tmp_path: Path):
    storage.configure(tmp_path)
    yield tmp_path


def _row(rid: str, *cells) -> dict:
    return {"id": rid, "cells": list(cells)}


def test_an_empty_project() -> None:
    view = client.get(URL).json()
    assert view["rows"] == [] and view["equipment_types"] == [] and view["parents"] == [] and view["errors"] == {}
    assert [c["heading"] for c in view["columns"]][:3] == ["Equipment Type Ref", "Area Ref", "Parent Equipment Ref"]
    assert (len(view["columns"]), view["columns"][8], view["columns"][0]["tag"]) == (43, {"key": "1", "heading": "#1", "tag": "<<#1>>"}, "<<STD>>")
    assert client.get("/api/keylists").json()["instrument_runsheet"] == {"items": 0}
    tags = client.get("/api/keylists/load-types/lists").json()["instrument_tags"]
    assert tags[0] == {"tag": "<<STD>>", "meaning": "the name of the row's equipment type"} and tags[-1]["tag"] == "<<#35>>"


def test_the_references_must_match_to_save() -> None:
    client.post("/api/sample-data")
    view = client.get(URL).json()
    assert view["equipment_types"] == ["Motor control centre", "Distribution board", "Centrifugal pump"] and "100" in view["areas"]
    assert {"P-101", "LP-601", "MCC-1", "MSB-1"} <= set(view["parents"])  # the MEL and the Electrical Equipment List
    assert [r["cells"][2] for r in view["rows"]] == ["P-101", "P-102", "P-103"] and view["rows"][0]["cells"][8] == "10101"

    bad = client.put(URL, json={"rows": [_row("r1", "No such type", "100", "P-101"), _row("r2", "Centrifugal pump", "999", "X-1"),
                                         _row("r3", "centrifugal  PUMP", 100, "mcc-1", "", "", "", "perhaps")]})
    assert bad.status_code == 422 and set(bad.json()["fields"]) == {"r1.equipment_type", "r2.area", "r2.parent", "r3.confirmed"}
    assert "Row 1 (No such type / P-101): 'No such type' is not an equipment type" in bad.json()["detail"]
    assert len(client.get(URL).json()["rows"]) == 3  # nothing was saved

    ann = client.get(URL, headers=ANN).headers["ETag"]
    bob = client.get(URL, headers=BOB).headers["ETag"]
    rows = [_row("r1", "centrifugal  PUMP", 100, "mcc-1", "", "100-U-PID-001", "**CV**-CPL1", "TRUE", 1001, 10335, "0042"), _row("r2")]
    ok = client.put(URL, json={"rows": rows}, headers={**ANN, "If-Match": ann})
    assert ok.status_code == 200, ok.text
    saved = ok.json()["rows"]
    assert len(saved) == 1 and saved[0]["cells"][:10] == ["Centrifugal pump", "100", "MCC-1", "", "100-U-PID-001", "**CV**-CPL1", "TRUE",
                                                         "1001", "10335", "0042"]
    assert client.get("/api/keylists").json()["instrument_runsheet"] == {"items": 1}
    stale = client.put(URL, json={"rows": []}, headers={**BOB, "If-Match": bob})
    assert stale.status_code == 409 and stale.json()["conflict"] is True
    assert "Instrument Runsheet" in str(client.get("/api/audit", params={"entity": "instrument_runsheet"}).json())


def test_what_a_row_refers_to_cannot_be_deleted_and_a_rename_follows() -> None:
    client.post("/api/sample-data")
    packages = client.get("/api/keylists/equipment-packages").json()
    without = {"items": packages["items"], "types": [t for t in packages["types"] if t["name"] != "Centrifugal pump"]}
    refused = client.put("/api/keylists/equipment-packages", json=without)
    assert refused.status_code == 422 and "Centrifugal pump (3 rows)" in refused.json()["detail"]
    areas = client.get("/api/keylists/plant-areas").json()["nodes"]
    refused = client.put("/api/keylists/plant-areas", json={"nodes": [n for n in areas if n["tag"] not in ("100", "B-110", "R-111", "PNL-111")]})
    assert refused.status_code == 422

    renamed = {"items": packages["items"], "types": [dict(t, name="Pump (centrifugal)") if t["name"] == "Centrifugal pump" else t
                                                      for t in packages["types"]]}
    assert client.put("/api/keylists/equipment-packages", json=renamed).status_code == 200
    view = client.get(URL).json()
    assert {r["cells"][0] for r in view["rows"]} == {"Pump (centrifugal)"} and view["errors"] == {}


def test_the_mel_list_is_every_row_of_the_imports_read_only() -> None:
    assert client.get("/api/mel-list").json() == {"headers": [], "rows": [], "sources": [], "warnings": []}
    client.post("/api/sample-data")
    rid = client.get("/api/mel/recipes").json()[0]["id"]
    recipe = client.get(f"/api/mel/recipes/{rid}").json()["recipe"]
    recipe["hidden_rows"] = [{"key": "LP-601"}]  # unticked as not a load: gone from the Load List, still in the MEL
    assert client.put(f"/api/mel/recipes/{rid}", json=recipe).status_code == 200
    mel = client.get("/api/mel-list").json()
    assert mel["headers"][:3] == ["Tag", "Area", "Description"] and len(mel["rows"]) == 9
    lp = next(r for r in mel["rows"] if r["key"] == "LP-601")
    assert (lp["source"], lp["tag"], lp["in_load_list"], lp["values"]["Description"]) == ("Sample plant MEL", "LP-601", False, "Lighting panel")
    assert sum(r["in_load_list"] for r in mel["rows"]) == 8 and client.get("/api/keylists").json()["mel"] == {"items": 9}
    assert "LP-601" in client.get(URL).json()["parents"]  # so it can be a parent in the runsheet

    data = client.post("/api/list-workbooks/mel/export", json={}).content
    ws = load_workbook(io.BytesIO(data))["MEL"]
    assert [c.value for c in ws[1]][:4] == ["Source", "Tag", "In the Load List", "Tag"] and ws.max_row == 10
    assert client.post("/api/list-workbooks/mel/import", params={"filename": "m.xlsx"}, content=data).status_code == 400
    assert client.post("/api/list-workbooks/mel/reset").status_code == 400

    sheet = client.post("/api/list-workbooks/instrument-runsheet/export", json={}).content
    ws = load_workbook(io.BytesIO(sheet))["Instrument Runsheet"]
    assert ws["A1"].value == "Equipment Type Ref" and ws["AQ1"].value == "#35" and ws["I2"].value == "10101" and ws.max_row == 4


def test_more_than_35_numbers() -> None:
    client.post("/api/sample-data")
    rows = client.get(URL).json()["rows"]
    rows[0]["cells"] = rows[0]["cells"][:8] + [str(n) for n in range(1, 39)]  # 38 numbers on one row
    saved = client.put(URL, json={"rows": rows})
    assert saved.status_code == 200, saved.text
    view = saved.json()
    assert len(view["columns"]) == 8 + 38 and view["columns"][-1] == {"key": "38", "heading": "#38", "tag": "<<#38>>"}
    assert [len(r["cells"]) for r in view["rows"]] == [46, 46, 46] and view["rows"][0]["cells"][-1] == "38" and view["max_numbers"] == 500
    assert client.get("/api/keylists/load-types/lists").json()["instrument_tags"][-1]["tag"] == "<<#38>>"

    data = client.post("/api/list-workbooks/instrument-runsheet/export", json={}).content
    ws = load_workbook(io.BytesIO(data))["Instrument Runsheet"]
    assert ws.max_column == 46 and ws.cell(1, 46).value == "#38" and ws.cell(2, 46).value == "38"
    assert client.put(URL, json={"rows": []}).status_code == 200
    back = client.post("/api/list-workbooks/instrument-runsheet/import", params={"filename": "r.xlsx", "apply": True}, content=data)
    assert back.status_code == 200 and back.json()["applied"], back.text
    assert client.get(URL).json()["rows"][0]["cells"][-1] == "38"
    rows[0]["cells"] = rows[0]["cells"][:8] + ["1"]  # narrower again: back to the usual 35 columns
    assert len(client.put(URL, json={"rows": rows}).json()["columns"]) == 43
