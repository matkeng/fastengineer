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


def test_settings_pass_between_people_as_a_json_file(tmp_path: Path) -> None:
    rid = client.post("/api/mel/recipes", json={"name": "Plant MEL", "target": "MEL"}).json()["id"]
    _upload(rid, "mel-sample.csv")
    recipe = client.get(f"/api/mel/recipes/{rid}").json()["recipe"]
    recipe["hidden_rows"] = [{"key": "P-101"}]
    recipe["mapping"] = [{"field": "tag", "column": "Equipment Tag"}]
    assert client.put(f"/api/mel/recipes/{rid}", json=recipe).status_code == 200

    out = tmp_path / "settings"
    assert client.post(f"/api/mel/recipes/{rid}/settings/export", json={"path": str(out)}).json() == {"path": str(out) + ".json"}
    doc = client.post(f"/api/mel/recipes/{rid}/settings/export", json={}).json()
    assert (doc["format"], doc["version"], doc["name"], doc["target"]) == ("drawing-workbench/list-import-settings", 1, "Plant MEL", "MEL")
    assert doc["settings"]["hidden_rows"] == [{"key": "P-101"}] and "id" not in doc and set(doc["settings"]) == {
        "columns", "hidden_rows", "text_columns", "overrides", "custom_rows", "auto_columns", "mapping"}

    # a colleague makes a new import from the file: same name (made unique here), settings, and no file yet
    new = client.post("/api/mel/settings/new", json=doc)
    assert new.status_code == 200, new.text
    made = new.json()
    assert made["id"] != rid and made["name"] == "Plant MEL (2)" and made["hidden_rows"] == [{"key": "P-101"}]
    assert client.get(f"/api/mel/recipes/{made['id']}").json()["revisions"] == []
    assert made["mapping"][0]["column"] == "Equipment Tag"

    # or reads it into an import they have: nothing is saved until they save
    other = client.post("/api/mel/recipes", json={"name": "Mine", "target": "MEL"}).json()
    read = client.post(f"/api/mel/recipes/{other['id']}/settings/read", json=doc).json()
    assert (read["id"], read["name"], read["hidden_rows"]) == (other["id"], "Mine", [{"key": "P-101"}])
    assert client.get(f"/api/mel/recipes/{other['id']}").json()["recipe"]["hidden_rows"] == []

    pil = client.post("/api/mel/recipes", json={"name": "Tags", "target": "PIL"}).json()
    wrong = client.post(f"/api/mel/recipes/{pil['id']}/settings/read", json=doc)
    assert wrong.status_code == 422 and "MEL import" in wrong.json()["detail"]
    assert client.post("/api/mel/settings/new", json={"hello": 1}).status_code == 422
    assert client.post("/api/mel/settings/new", json=doc | {"version": 2}).status_code == 422
    damaged = client.post("/api/mel/settings/new", json=doc | {"settings": {"hidden_rows": "nope"}})
    assert damaged.status_code == 422 and "damaged" in damaged.json()["detail"]


def test_the_function_help() -> None:
    help_ = client.get("/api/mel/functions").json()
    assert [g["name"] for g in help_["groups"]] == ["Columns and values", "Comparisons and logic", "Numbers", "Text"]
    assert help_["sample_row"]["Tag"] == "P-101"
    text = next(g for g in help_["groups"] if g["name"] == "Text")
    assert {"expression": "<<Tag>>.replace('-', '')", "result": "P101", "what": "replace every occurrence"} in text["examples"]
    assert not any("open" in e["expression"] for g in help_["groups"] for e in g["examples"])
