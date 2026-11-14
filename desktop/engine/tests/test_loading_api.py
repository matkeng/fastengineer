# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""The Board Loading API."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from workbench_desktop import storage
from workbench_desktop.app import app

client = TestClient(app)
API = "/api/loading"


@pytest.fixture(autouse=True)
def data_dir(tmp_path: Path):
    storage.configure(tmp_path)
    yield tmp_path


def test_the_sample_projects_boards_and_the_export() -> None:
    assert client.get(API).json()["boards"] == []  # an empty project
    assert client.post("/api/sample-data").status_code == 200
    rep = client.get(API).json()
    assert [(b["tag"], b["depth"], b["supplied_from"], b["loads"]) for b in rep["boards"]] == [
        ("MSB-1", 0, "Primary Supply", 9), ("MCC-1", 1, "MSB-1", 4), ("MCC-2", 1, "MSB-1", 5)]
    msb = rep["boards"][0]
    # 165 kW connected (as the Load List Summary test); the Default factors: nameplate 0.75, maximum 1; 0.85 power factor
    assert (msb["connected_kw"], msb["max_kw"], msb["max_kva"]) == (165, 123.75, round(123.75 / 0.85, 2))
    amps = 123.75 / 0.85 * 1000 / (3 ** 0.5 * 415)
    assert msb["max_amps"] == round(amps, 1) and (msb["rating"], msb["rating_unit"]) == (1600, "Amps")
    assert msb["loading_pct"] == round(amps / 1600 * 100, 1) and msb["over"] is False and rep["left_out"] == []
    assert client.get(API, params={"warn_at": 10}).json()["boards"][0]["over"] is True
    assert client.get(API, params={"warn_at": 0}).status_code == 422

    wb = load_workbook(io.BytesIO(client.post(f"{API}/export", json={"warn_at": 10}).content))
    assert wb.sheetnames == ["Boards", "Not counted", "Notes"]
    rows = [list(r) for r in wb["Boards"].iter_rows(values_only=True)]
    assert rows[0][:5] == ["Board", "Description", "Level", "Supplied from", "Loads"] and rows[1][0] == "MSB-1"
    assert rows[1][rows[0].index("Problems")] == "At or above 10 %" and rows[2][rows[0].index("Loading %")] == rep["boards"][1]["loading_pct"]
