# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""The project's fields of the Project Master Load List: edit them, and the import mapping
sheet, the Load List and its workbook follow."""

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
API = "/api/load-fields"


@pytest.fixture(autouse=True)
def data_dir(tmp_path: Path):
    storage.configure(tmp_path)
    yield tmp_path


def _fields() -> list[dict]:
    return client.get(API).json()["fields"]


def _put(fields: list[dict], dry_run: bool = False):
    return client.put(API, params={"dry_run": dry_run}, json={"fields": fields})


def _import(mapping: list[dict]) -> str:
    rid = client.post("/api/mel/recipes", json={"name": "Plant MEL", "target": "MEL"}).json()["id"]
    recipe = client.get(f"/api/mel/recipes/{rid}").json()["recipe"]
    assert client.put(f"/api/mel/recipes/{rid}", json=recipe | {"mapping": mapping}).status_code == 200
    res = client.post(f"/api/mel/recipes/{rid}/revisions/csv", params={"filename": "f.csv", "key": "Equipment Tag"},
                      content=(SAMPLES / "mel-sample.csv").read_bytes())
    assert res.status_code == 200, res.text
    return rid


def test_the_built_in_fields_until_changed_and_what_is_refused() -> None:
    fields = _fields()
    assert [f["key"] for f in fields][:3] == ["area", "sub_area", "tag"] and fields[2] == {"key": "tag", "label": "Tag", "kind": "text", "locked": True, "calc": None}
    assert next(f for f in fields if f["key"] == "load_rating")["kind"] == "number"
    assert next(f for f in fields if f["key"] == "starter_type")["locked"] is False

    def refused(edited: list[dict]) -> str:
        res = _put(edited)
        assert res.status_code == 422, res.text
        return " ".join(res.json()["fields"].values())

    assert "not deleted: Tag" in refused([f for f in fields if f["key"] != "tag"])
    assert "keeps its kind" in refused([f | {"kind": "text"} if f["key"] == "load_rating" else f for f in fields])
    assert "twice" in refused([*fields, {"key": "", "label": "tag", "kind": "text"}])
    assert "needs a name" in refused([*fields, {"key": "", "label": " ", "kind": "text"}])
    assert "not a field" in refused([*fields, {"key": "nope", "label": "Nope", "kind": "text"}])
    assert _fields() == fields  # nothing was saved


def test_fields_flow_into_the_mapping_sheet_the_load_list_and_its_workbook() -> None:
    rid = _import([{"field": "tag", "column": "Equipment Tag"}, {"field": "desc", "column": "Description"},
                   {"field": "starter_type", "column": "Notes"}, {"field": "standby_qty", "column": "Standby"}])
    detail = client.get(f"/api/mel/recipes/{rid}").json()
    assert detail["fields"][:3] == ["area", "sub_area", "tag"] and detail["labels"]["desc"] == "Description"

    fields = _fields()
    edited = [f | {"label": "Item description"} if f["key"] == "desc" else f for f in fields if f["key"] != "starter_type"]
    edited.insert(0, edited.pop(next(i for i, f in enumerate(edited) if f["key"] == "tag")))  # Tag first
    edited += [{"key": "", "label": "Motor HP", "kind": "number"}, {"key": "", "label": "Rating", "kind": "text"}]

    dry = _put(edited, dry_run=True)
    assert dry.status_code == 200, dry.text
    impact = dry.json()["impact"]
    assert impact["relabelled"] == {"desc": ["Description", "Item description"]} and impact["added"] == ["Motor HP", "Rating"]
    assert impact["reordered"] is True
    gone = impact["deleted"]
    assert [(d["key"], d["imports"]) for d in gone] == [("starter_type", ["Plant MEL"])] and gone[0]["rows"] == 4  # the Notes column has text in 4 rows
    assert any(f["key"] == "starter_type" for f in _fields())  # nothing changed yet

    saved = _put(edited)
    assert saved.status_code == 200 and saved.json()["saved"] is True, saved.text
    keys = [f["key"] for f in _fields()]
    assert keys[0] == "tag" and keys[-2:] == ["motor_hp", "rating_2"] and "starter_type" not in keys  # 'rating' is a <<tag>> of its own

    # the mapping sheet offers the new fields, labelled; the deleted field's mapping is gone
    detail = client.get(f"/api/mel/recipes/{rid}").json()
    assert detail["fields"][0] == "tag" and "motor_hp" in detail["fields"] and detail["labels"]["motor_hp"] == "Motor HP"
    assert [m["field"] for m in detail["recipe"]["mapping"]] == ["tag", "desc", "standby_qty"]
    recipe = detail["recipe"]
    recipe["mapping"].append({"field": "motor_hp", "column": "Motor HP", "manual": None})
    assert client.put(f"/api/mel/recipes/{rid}", json=recipe).status_code == 200

    # the Load List: the new field's values, a number, labelled; the import's own output too
    view = client.get("/api/loadlist").json()
    assert view["fields"] == ["tag", "standby_qty", "desc", "motor_hp"] and view["labels"]["desc"] == "Item description"
    p101 = next(r for r in view["rows"] if r["key"] == "P-101")
    assert p101["values"]["motor_hp"] == 40 and "starter_type" not in p101["values"]
    out = client.post(f"/api/mel/recipes/{rid}/loadlist", json={}).json()
    assert "motor_hp" in out["fields"]

    # a load type's row can use the new field as a tag
    assert client.put("/api/keylists/load-types", json={"items": [
        {"id": "t1", "code": "PUMP", "name": "Pump", "rating_unit": "kW", "voltage": 460, "phases": "AC-3-phase",
         "rows": {"equipment_list": [{"Tag": "<<Tag>>", "Rating": "<<motor_hp>> HP"}]}}]}).status_code == 200
    rows = client.get("/api/loadlist").json()["rows"]
    assert client.put("/api/loadlist/allocations", json={"rows": [{"recipe_id": r["recipe_id"], "key": r["key"]} for r in rows],
                                                          "load_type_id": "t1"}).status_code == 200
    master = client.get("/api/master/equipment_list").json()["result"]
    assert ["P-101", "40 HP"] in [[r["cells"][0], r["cells"][master["header"].index("Rating")]] for r in master["rows"]]

    # the workbook's reference columns are headed by the labels
    wb = load_workbook(io.BytesIO(client.post("/api/list-workbooks/load-list/export", json={}).content))
    head = [c.value for c in wb.active[1]]
    assert "Motor HP" in head and "Standby quantity" in head and "motor_hp" not in head


def test_a_load_list_deliverable_has_every_column_and_follows_the_fields() -> None:
    assert client.post("/api/sample-data").status_code == 200
    cols = client.get("/api/deliverables").json()["project_columns"]["Load List"]
    assert cols[:2] == ["Tag", "Description"] and "Cable Size" in cols and "Load rating" in cols and "Starter type" in cols
    made = client.post("/api/deliverables", json={"type": "Load List", "name": "Loads with starters", "source": "project",
                                                  "columns": ["Tag", "Load rating", "Starter type", "Cable Size"],
                                                  "filter_column": "Starter type", "filter_values": ["DOL"]})
    assert made.status_code == 200, made.text
    cur = client.get(f"/api/deliverables/{made.json()['id']}", params={"rows": True}).json()["current"]
    assert cur["result"]["header"] == ["Tag", "Load rating", "Starter type", "Cable Size"]

    fields = _fields()
    edited = [f | {"label": "Motor rating"} if f["key"] == "load_rating" else f for f in fields if f["key"] != "starter_type"]
    assert _put(edited).status_code == 200
    d = client.get(f"/api/deliverables/{made.json()['id']}", params={"rows": True}).json()
    assert d["deliverable"]["columns"] == ["Tag", "Motor rating", "Cable Size"] and d["deliverable"]["filter_column"] == ""
    assert d["current"]["result"]["header"] == ["Tag", "Motor rating", "Cable Size"]


def test_an_existing_load_list_deliverable_keeps_its_ten_columns(data_dir: Path) -> None:
    import sqlite3

    assert client.post("/api/sample-data").status_code == 200
    ll = next(s["deliverable"] for s in client.get("/api/deliverables").json()["deliverables"] if s["deliverable"]["type"] == "Load List")
    assert ll["columns"] == []  # a new one shows every column
    # as it was before the update: the flag not yet set
    db = sqlite3.connect(next(data_dir.rglob("workbench.db")))
    db.execute("DELETE FROM settings WHERE key = 'load_list_columns_v2'")
    db.commit()
    db.close()
    storage.configure(data_dir)
    ll = client.get(f"/api/deliverables/{ll['id']}").json()["deliverable"]
    assert ll["columns"] == ["Tag", "Description", "Plant Area", "Load Type", "Rating", "Units", "Voltage", "Phases",
                             "Supplied From", "Distribution Panel"]


def test_calculated_fields() -> None:
    assert client.post("/api/sample-data").status_code == 200
    fields = _fields()
    calc = {"key": "", "label": "Active power (kW)", "kind": "calc",
            "calc": {"applies_if": "<<load_rating>> != ''", "formula": "<<load_rating>> * 0.746 if <<units>> == 'HP' else <<load_rating>>",
                     "decimals": 2, "checks": [{"rule": "<<value>> < 100", "message": "Over 100 kW", "severity": "warning"}]}}
    amps = {"key": "", "label": "Rated current (A)", "kind": "calc",
            "calc": {"formula": "<<active_power_kw>> * 1000 / (sqrt(3) * <<voltage>> * 0.85)", "decimals": 1,
                     "checks": [{"rule": "<<value>> > 0", "message": "", "severity": "error"}]}}
    edited = [*fields, calc, amps]

    # refused: a field that isn't there, and no formula
    bad = _put([*fields, calc | {"calc": calc["calc"] | {"formula": "<<nope>> * 2"}}])
    assert bad.status_code == 422 and "not a field" in bad.json()["fields"][f"{len(fields)}.formula"]
    assert _put([*fields, calc | {"calc": None}]).json()["fields"][f"{len(fields)}.formula"] == "A calculated field needs a formula"

    # a preview of the unsaved calculation, on the Load List as it is now
    pre = client.post(f"{API}/preview", json={"fields": edited, "field": len(edited) - 1})
    assert pre.status_code == 200, pre.text
    p = pre.json()
    assert p["total"] == 12 and p["errors"] == 0
    c401 = next(r for r in p["rows"] if r["tag"] == "C-401")
    assert c401["value"] == round(75 * 1000 / (3 ** 0.5 * 415 * 0.85), 1)
    assert client.get(API).json()["fields"][-1]["kind"] != "calc"  # nothing saved

    saved = _put(edited)
    assert saved.status_code == 200, saved.text
    view = client.get(API).json()
    assert view["fields"][-1]["calc"]["formula"].startswith("<<active_power_kw>>") and "sqrt" in view["functions"]
    assert any(r["ref"] == "<<loadtype>>" for r in view["app_refs"])

    # the Load List shows the answers, and what fails a check
    ll = client.get("/api/loadlist").json()
    assert ll["calculated"] == ["active_power_kw", "rated_current_a"] and "rated_current_a" in ll["fields"]
    rows = {r["key"]: r for r in ll["rows"]}
    assert rows["C-401"]["values"]["active_power_kw"] == 75 and rows["C-401"]["values"]["rated_current_a"] == c401["value"]
    big = {r["key"] for r in ll["rows"] if isinstance(r["values"]["active_power_kw"], (int, float)) and r["values"]["active_power_kw"] >= 100}
    assert {r["key"] for r in ll["rows"] if any(i["message"] == "Over 100 kW" for i in r["calc_issues"])} == big

    # calculated fields aren't import targets, but are columns of a Load List deliverable and tags for load types' rows
    rid = client.get("/api/mel/recipes").json()[0]["id"]
    assert "active_power_kw" not in client.get(f"/api/mel/recipes/{rid}").json()["fields"]
    assert "Rated current (A)" in client.get("/api/deliverables").json()["project_columns"]["Load List"]
    made = client.post("/api/deliverables", json={"type": "Load List", "name": "Currents", "source": "project",
                                                  "columns": ["Tag", "Active power (kW)", "Rated current (A)"]})
    cur = client.get(f"/api/deliverables/{made.json()['id']}", params={"rows": True}).json()["current"]
    assert ["C-401", 75, c401["value"]] in [r["cells"] for r in cur["result"]["rows"]]

    # a field a calculation uses can't be deleted
    rating_used = _put([f for f in client.get(API).json()["fields"] if f["key"] != "active_power_kw"])
    assert rating_used.status_code == 422 and "<<active_power_kw>>" in " ".join(rating_used.json()["fields"].values())
