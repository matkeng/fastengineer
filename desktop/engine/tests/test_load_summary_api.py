# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""The Load List Summary Page API."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from workbench_desktop import storage
from workbench_desktop.app import app

client = TestClient(app)
API = "/api/load-summary"
PAGE = {"tables": [{"name": "Switchboard loading", "filter": "not <<ispanel>>", "rows": [
    {"name": "MSB-1", "condition": "'MSB-1' in <<supplychain>>", "ref_tag": "MSB-1"},
    {"name": "MCC-1", "condition": "<<suppliedfrom>> == 'MCC-1'"}], "columns": [
    {"name": "kW", "func": "sum", "field": "load_rating", "condition": "<<units>> == 'kW'"},
    {"name": "Count", "func": "count"},
    {"name": "% of rating", "kind": "formula", "formula": "<<kW>> / (sqrt(3) * 0.415 * <<Ref.load_rating>>) * 100",
     "applies_if": "<<Ref.load_rating>> != ''", "otherwise": "''", "decimals": 1}]}]}


@pytest.fixture(autouse=True)
def data_dir(tmp_path: Path):
    storage.configure(tmp_path)
    yield tmp_path


def test_save_work_out_preview_and_export() -> None:
    empty = client.get(API).json()
    assert empty["page"] == {"tables": []} and empty["tables"] == [] and empty["funcs"]["average"] == "Average"
    assert any(c["key"] == "supplychain" for c in empty["refs"]) and any(c["key"] == "load_rating" for c in empty["fields"])
    assert client.post("/api/sample-data").status_code == 200

    pre = client.post(f"{API}/preview", json=PAGE)
    assert pre.status_code == 200, pre.text
    assert client.get(API).json()["page"] == {"tables": []}  # a preview saves nothing
    saved = client.put(API, json=PAGE)
    assert saved.status_code == 200, saved.text
    (t,) = saved.json()["tables"]
    rows = {r["name"]: r for r in t["rows"]}
    # MSB-1 feeds MCC-1 and MCC-2, which feed the motors (kW) and the lighting panel
    assert rows["MSB-1"]["cells"][0] == 75 + 4 + 4 + 12 + 10 + 15 + 7.5 + 7.5 + 30 and rows["MSB-1"]["loads"] == 9
    assert rows["MSB-1"]["cells"][2] == round(165 / (3 ** 0.5 * 0.415 * 1600) * 100, 1)
    assert rows["MCC-1"]["cells"][:2] == [60, 4] and rows["MCC-1"]["cells"][2] == ""
    assert rows["Total"]["cells"][1] == 9

    bad = client.put(API, json={"tables": [{"name": "T", "filter": "<<nope>>"}]})
    assert bad.status_code == 422 and "<<nope>>" in bad.json()["fields"]["0.filter"]

    wb = load_workbook(io.BytesIO(client.post(f"{API}/export", json={}).content))
    assert wb.sheetnames == ["Switchboard loading"]
    sheet = [list(r) for r in wb["Switchboard loading"].iter_rows(values_only=True)]
    assert sheet[0] == ["Row", "kW", "Count", "% of rating", "Loads", "Problems"] and sheet[1][0] == "MSB-1"
