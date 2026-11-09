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


def _upload(rid: str, name: str, key: str = "Equipment Tag"):
    res = client.post(f"/api/mel/recipes/{rid}/revisions/csv", params={"filename": name, "key": key},
                      content=(SAMPLES / name).read_bytes())
    assert res.status_code == 200, res.text
    return res.json()


def test_mel_flow_persists_and_reapplies(data_dir: Path) -> None:
    rid = client.post("/api/mel/recipes", json={"name": "Plant MEL", "target": "MEL"}).json()["id"]
    assert client.post(f"/api/mel/recipes/{rid}/run", json={"stage": "auto"}).status_code == 409  # no file yet

    insp = client.post("/api/mel/csv/inspect", content=(SAMPLES / "mel-sample.csv").read_bytes()).json()
    assert insp["suggested_key"] == "Equipment Tag" and insp["num_rows"] == 8
    rev1 = _upload(rid, "mel-sample.csv")
    assert rev1["rev"] == 1 and "made unique" in rev1["warnings"][0]

    recipe = client.get(f"/api/mel/recipes/{rid}").json()["recipe"]
    recipe["columns"] = [{"header": "Notes_1", "visible": False}, {"header": "Blank", "visible": False}]
    recipe["hidden_rows"] = [{"key": "Blank"}, {"key": "P-102_1"}]
    recipe["text_columns"] = [{"name": "Source", "value": "MEL"}]
    recipe["auto_columns"] = [{"name": "kW", "statement": "<<Motor HP>> != ''",
                               "true_val": "round(<<Motor HP>> * 0.746, 1)", "false_val": "0", "error_val": "?"}]
    recipe["mapping"] = [{"field": "tag", "column": "Equipment Tag"}, {"field": "load_rating", "column": "kW"},
                         {"field": "load_units", "manual": "kW"}]
    assert client.put(f"/api/mel/recipes/{rid}", json=recipe).status_code == 200

    # "Re-run": reopen the database from disk, as after an app restart.
    storage.configure(data_dir)
    saved = client.get(f"/api/mel/recipes/{rid}").json()
    assert saved["recipe"]["text_columns"][0]["name"] == "Source" and len(saved["revisions"]) == 1

    out = client.post(f"/api/mel/recipes/{rid}/run", json={"stage": "auto"}).json()
    assert len(out["rows"]) == 6 and out["headers"][-2:] == ["Source", "kW"] and out["issues"] == []
    ll = client.post(f"/api/mel/recipes/{rid}/loadlist", json={}).json()
    assert ll["fields"] == ["tag", "load_units", "load_rating"]
    assert {r["tag"]: r["load_rating"] for r in ll["rows"]}["P-101"] == 29.8

    # Revised MEL: same recipe applies to the new file; dead rules are reported.
    assert _upload(rid, "mel-sample-rev2.csv")["rev"] == 2
    out2 = client.post(f"/api/mel/recipes/{rid}/run", json={"stage": "auto"}).json()
    assert {r["key"] for r in out2["rows"]} >= {"P-601"} and len(out2["rows"]) == 6
    assert {i["kind"] for i in out2["issues"]} == {"columns", "rows"}

    # Draft preview without saving.
    draft = {**saved["recipe"], "text_columns": []}
    assert "Source" not in client.post(f"/api/mel/recipes/{rid}/run", json={"stage": "auto", "recipe": draft}).json()["headers"]

    # Export.
    res = client.post(f"/api/mel/recipes/{rid}/export", json={"table": "loadlist", "format": "xlsx"})
    wb = load_workbook(io.BytesIO(res.content))
    assert wb.sheetnames == ["Load list", "Notes"] and wb["Load list"].max_row == 7
    res = client.post(f"/api/mel/recipes/{rid}/export", json={"table": "combined", "format": "csv"})
    assert res.content.startswith(b"\xef\xbb\xbfEquipment Tag,")
    target = data_dir / "out"
    res = client.post(f"/api/mel/recipes/{rid}/export", json={"table": "combined", "format": "xlsx", "path": str(target)})
    assert res.json()["path"].endswith("out.xlsx") and (data_dir / "out.xlsx").exists()

    assert client.delete(f"/api/mel/recipes/{rid}").status_code == 200
    assert client.get(f"/api/mel/recipes/{rid}").status_code == 404


def test_excel_source() -> None:
    rid = client.post("/api/mel/recipes", json={"name": "From Excel", "target": "ELL"}).json()["id"]
    wb = client.post("/api/excel/workbooks", params={"filename": "cable-schedule-sample.xlsx"},
                     content=(SAMPLES / "cable-schedule-sample.xlsx").read_bytes()).json()
    res = client.post(f"/api/mel/recipes/{rid}/revisions/excel", json={
        "workbook_id": wb["id"], "source": "sheet:Cable Schedule", "header_row": 4, "header_rows": 2,
        "key_column": 0})
    assert res.status_code == 200, res.text
    assert res.json()["key_header"] == "Cable Tag" and res.json()["source"] == "excel: Cable Schedule"
