# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from workbench_desktop.app import app

XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
SAMPLE = Path(__file__).resolve().parents[3] / "samples" / "cable-schedule-sample.xlsx"
client = TestClient(app)


@pytest.mark.skipif(not SAMPLE.exists(), reason="sample workbook not generated")
def test_wizard_flow() -> None:
    res = client.post("/api/excel/workbooks", params={"filename": SAMPLE.name},
                      content=SAMPLE.read_bytes(),
                      headers={"Content-Type": "application/octet-stream"})
    assert res.status_code == 200, res.text
    wb = res.json()
    src = wb["sources"][0]["id"]

    pv = client.get(f"/api/excel/workbooks/{wb['id']}/preview", params={"source": src}).json()
    hr, depth = pv["suggested_header_row"], pv["suggested_header_rows"]

    cols = client.get(f"/api/excel/workbooks/{wb['id']}/columns",
                      params={"source": src, "header_row": hr, "header_rows": depth}).json()
    ex = client.post(f"/api/excel/workbooks/{wb['id']}/extract", json={
        "source": src, "header_row": hr, "header_rows": depth, "key_column": cols["suggested_key"],
    }).json()
    assert ex["rows"][0]["key"] == "CB-0401"
    assert ex["duplicate_keys"] == ["CB-0412"]

    assert client.delete(f"/api/excel/workbooks/{wb['id']}").status_code == 200
    assert client.get(f"/api/excel/workbooks/{wb['id']}/preview",
                      params={"source": src}).status_code == 404


def test_errors() -> None:
    res = client.post("/api/excel/workbooks", params={"filename": "a.xls"}, content=b"junk")
    assert res.status_code == 400 and ".xlsx" in res.json()["detail"]
    res = client.post("/api/excel/workbooks", params={"filename": "a.xlsx"}, content=b"junk")
    assert res.status_code == 400


REV_D = SAMPLE.with_name("cable-schedule-sample-revD.xlsx")


def _open(path: Path) -> str:
    res = client.post("/api/excel/workbooks", params={"filename": path.name}, content=path.read_bytes())
    assert res.status_code == 200, res.text
    return res.json()["id"]


@pytest.mark.skipif(not REV_D.exists(), reason="sample workbooks not generated")
def test_compare_flow() -> None:
    spec = {"source": "sheet:Cable Schedule", "header_row": 4, "header_rows": 2, "key_column": 0}
    res = client.post("/api/excel/compare", json={
        "a": {**spec, "workbook_id": _open(SAMPLE)},
        "b": {**spec, "workbook_id": _open(REV_D)},
    })
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["summary"]["added"] == 1 and body["summary"]["struck"] == 1
    assert body["a_label"] == "cable-schedule-sample.xlsx · Cable Schedule"

    gone = client.post("/api/excel/compare", json={
        "a": {**spec, "workbook_id": "nope"}, "b": {**spec, "workbook_id": "nope"}})
    assert gone.status_code == 404


@pytest.mark.skipif(not REV_D.exists(), reason="sample workbooks not generated")
def test_compare_export(tmp_path: Path) -> None:
    from openpyxl import load_workbook

    spec = {"source": "sheet:Cable Schedule", "header_row": 4, "header_rows": 2, "key_column": 0}
    body = {"a": {**spec, "workbook_id": _open(SAMPLE)}, "b": {**spec, "workbook_id": _open(REV_D)},
            "statuses": ["added", "deleted", "struck", "restored", "changed"]}
    res = client.post("/api/excel/compare/export", json=body)
    assert res.status_code == 200 and res.headers["content-type"].startswith(XLSX_TYPE)
    wb = load_workbook(io.BytesIO(res.content))
    assert wb["Differences"].max_row == 1 + 8  # header + rows with changes

    target = tmp_path / "out"  # extension added
    res = client.post("/api/excel/compare/export", json={**body, "path": str(target)})
    assert res.status_code == 200 and res.json()["path"].endswith("out.xlsx")
    assert (tmp_path / "out.xlsx").stat().st_size > 1000

    res = client.post("/api/excel/compare/export", content=json.dumps(body),
                      headers={"Content-Type": "text/plain"})
    assert res.status_code in (415, 422)  # no simple (non-preflighted) writes
