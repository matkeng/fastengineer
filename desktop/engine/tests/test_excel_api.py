from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from workbench_desktop.app import app

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
