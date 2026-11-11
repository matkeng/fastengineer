# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""The report of the edits a MEL import makes to its file (mel.edits_report)."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from workbench_desktop import storage
from workbench_desktop.app import app

SAMPLES = Path(__file__).resolve().parents[3] / "samples"
client = TestClient(app)


@pytest.fixture(autouse=True)
def data_dir(tmp_path: Path):
    storage.configure(tmp_path)
    yield tmp_path


def _sheet(wb, title: str) -> list[list]:
    return [list(r) for r in wb[title].iter_rows(values_only=True)]


def test_the_report_lists_changed_removed_and_added_rows_with_their_reasons() -> None:
    rid = client.post("/api/mel/recipes", json={"name": "Plant MEL", "target": "MEL"}).json()["id"]
    res = client.post(f"/api/mel/recipes/{rid}/revisions/csv", params={"filename": "mel rev B.csv", "key": "Equipment Tag"},
                      content=(SAMPLES / "mel-sample.csv").read_bytes())
    assert res.status_code == 200, res.text
    recipe = client.get(f"/api/mel/recipes/{rid}").json()["recipe"]
    recipe |= {
        "columns": [{"header": "Motor HP", "visible": True, "rename": "HP"}],
        "overrides": [{"key": "P-101", "column": "HP", "value": "50", "note": "Upsized per vendor data"},
                      {"key": "P-102", "column": "Description", "value": "Feed pump B (duty)"},
                      {"key": "GONE-1", "column": "HP", "value": "1", "note": "old"}],
        "hidden_rows": [{"key": "TK-501", "note": "Tank, not a load"}],
        "custom_rows": [{"key": "MCC-9", "values": {"Description": "New MCC", "HP": "0"}, "note": "Missing from the MEL"}],
    }
    assert client.put(f"/api/mel/recipes/{rid}", json=recipe).status_code == 200
    out = client.post(f"/api/mel/recipes/{rid}/edits-report", json={})
    assert out.status_code == 200, out.text
    assert "Plant MEL - edits to mel rev B.csv rev 1.xlsx" in out.headers["content-disposition"]
    wb = load_workbook(io.BytesIO(out.content))
    assert wb.sheetnames == ["Summary", "Changed cells", "Removed rows", "Added rows"]
    summary = dict((r[0], r[1]) for r in _sheet(wb, "Summary") if r and r[0])
    assert summary["File"] == "mel rev B.csv" and summary["Changed cells"] == 3 and summary["Removed rows"] == 1
    changed = _sheet(wb, "Changed cells")
    assert changed[0][:6] == ["Equipment Tag", "Column", "Column in the file", "Value in the file", "Value used", "Reason"]
    assert changed[1][:7] == ["P-101", "HP", "Motor HP", 40, 50, "Upsized per vendor data", 1]  # named as in the file
    assert changed[2][3:5] == ["Feed pump B", "Feed pump B (duty)"] and changed[2][5] is None and changed[2][6] == 2
    assert changed[3][0] == "GONE-1" and changed[3][7] == "Row not in the latest file"
    removed = _sheet(wb, "Removed rows")
    assert removed[1][:3] == ["TK-501", "Tank, not a load", 6] and "Storage tank" in removed[1]
    added = _sheet(wb, "Added rows")
    assert added[0][:3] == ["Equipment Tag", "Reason", "Status"] and added[1][:2] == ["MCC-9", "Missing from the MEL"]
    assert "New MCC" in added[1]
    # the editor's unsaved import can be reported too
    draft = recipe | {"hidden_rows": []}
    wb = load_workbook(io.BytesIO(client.post(f"/api/mel/recipes/{rid}/edits-report", json={"recipe": draft}).content))
    assert len(_sheet(wb, "Removed rows")) == 1
