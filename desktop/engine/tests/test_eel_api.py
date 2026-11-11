# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from workbench_desktop import storage
from workbench_desktop.app import app

SAMPLES = Path(__file__).resolve().parents[3] / "samples"
client = TestClient(app)
ANN = {"X-Workbench-User": "ACME\\ann", "X-Workbench-Machine": "PC-01"}
BOB = {"X-Workbench-User": "ACME\\bob", "X-Workbench-Machine": "PC-02"}
MAPPING = [{"field": "area", "column": "Area"}, {"field": "tag", "column": "Equipment Tag"},
           {"field": "desc", "column": "Description"}, {"field": "supplied_from", "manual": "MCC-1"}]


@pytest.fixture(autouse=True)
def data_dir(tmp_path: Path):
    storage.configure(tmp_path)
    client.put("/api/keylists/plant-areas", json={"nodes": [
        {"id": "a1", "tag": "100", "description": "Feed area", "area_type": "Area"},
        {"id": "a2", "tag": "200", "description": "Mixing area", "area_type": "Area"}]})
    client.put("/api/keylists/load-types", json={"items": [
        {"id": "t1", "code": "MCC", "name": "Motor control centre", "rating_unit": "Amps", "voltage": 415, "phases": "AC-3-phase"}]})
    client.put("/api/keylists/equipment-codes", json={"items": [{"id": "c1", "code": "MCC", "name": "MCC"},
                                                                {"id": "c2", "code": "DB", "name": "Distribution board"}]})
    client.put("/api/keylists/equipment-packages", json={"items": [
        {"id": "p1", "number": "PKG-010", "description": "Switchgear", "package_type": "Vendor"},
        {"id": "p2", "number": "PKG-020", "description": "Electrical installation", "package_type": "Installer"}]})
    yield tmp_path


def _item(i: str, tag: str, **more) -> dict:
    return {"id": i, "tag": tag, "description": f"{tag} board", "equipment_code_id": "c1", "plant_area_id": "a1"} | more


def _mel() -> str:
    rid = client.post("/api/mel/recipes", json={"name": "Plant MEL", "target": "MEL"}).json()["id"]
    recipe = client.get(f"/api/mel/recipes/{rid}").json()["recipe"]
    client.put(f"/api/mel/recipes/{rid}", json=recipe | {"mapping": MAPPING})
    r = client.post(f"/api/mel/recipes/{rid}/revisions/csv", params={"filename": "f.csv", "key": "Equipment Tag"},
                    content=(SAMPLES / "mel-sample.csv").read_bytes())
    assert r.status_code == 200
    return rid


def _ll() -> dict[str, dict]:
    return {r["values"].get("tag") or r["key"]: r for r in client.get("/api/loadlist").json()["rows"]}


def test_eel_items_rules_and_the_load_list(data_dir: Path) -> None:
    view = client.get("/api/eel").json()
    assert view["items"] == [] and [c["label"] for c in view["choices"]["supplies"]] == ["Primary Supply"]
    assert view["choices"]["load_types"][0] | {} == {"id": "t1", "label": "MCC – Motor control centre", "depth": 0,
                                                     "rating_unit": "Amps", "voltage": 415, "phases": "AC-3-phase"}
    mel = _mel()

    items = [_item("i1", "MCC-1", is_panel=True, supplied_from="primary", load_type_id="t1", rating_unit="Amps",
                   voltage="415", phases="AC-3-phase", rating="630", manufacturer="ACME", model_number="X-1",
                   vendor_package_id="p1", supplied_by_id="p1", installed_by_id="p2", terminated_by_id="p2"),
             _item("i2", "DB-1", equipment_code_id="c2", plant_area_id="a2", supplied_from="eel/i1")]
    r = client.put("/api/eel", json={"items": items})
    assert r.status_code == 200, r.text
    assert [c["label"] for c in r.json()["choices"]["supplies"]] == ["Primary Supply", "MCC-1 – MCC-1 board"]

    # Required, unique here and across the imports' tags.
    bad = client.put("/api/eel", json={"items": items + [_item("i3", "mcc-1"), _item("i4", "p-101 ", plant_area_id=""),
                                                         {"id": "i5", "tag": "X"}]})
    assert bad.status_code == 422
    f = bad.json()["fields"]
    assert f["i3.tag"] == "Tag number 'mcc-1' is used twice" and f["i4.tag"] == "Tag p-101 is already in Plant MEL"
    assert {"i4.plant_area_id", "i5.description", "i5.equipment_code_id", "i5.plant_area_id"} <= set(f)

    # The items are Load List rows: their allocations come from here and can't be changed there.
    ll = _ll()
    mcc, db = ll["MCC-1"], ll["DB-1"]
    assert (mcc["source"], mcc["plant_area_id"], mcc["plant_area_by"], mcc["load_type_id"], mcc["is_panel"]) == (
        "Electrical Equipment List", "a1", "eel", "t1", True)
    assert (mcc["supplied_from"], db["supplied_from"], db["plant_area_id"]) == ("primary", "eel/i1", "a2")
    assert (mcc["values"]["equip_type"], mcc["values"]["load_voltage"], mcc["values"]["load_rating"]) == ("MCC", 415, 630)
    refused = client.put("/api/loadlist/allocations", json={"rows": [{"recipe_id": "eel", "key": "i1"}], "plant_area_id": "a2"})
    assert refused.status_code == 422 and "Electrical Equipment List" in refused.json()["detail"]
    # A MEL row's "supplied from MCC-1" text finds the EEL panel.
    p101 = ll["P-101"]
    assert (p101["supplied_from"], p101["supplied_from_by"]) == ("eel/i1", "auto")

    # A person supplies M-204 from MCC-1: MCC-1 can't stop being a panel, or be deleted.
    m204 = ll["M-204"]
    assert client.put("/api/loadlist/allocations", json={"rows": [{"recipe_id": mel, "key": "M-204"}],
                                                         "supplied_from": "eel/i1"}).status_code == 200
    no = client.put("/api/eel", json={"items": [dict(items[0], is_panel=False), dict(items[1], supplied_from=None)]})
    assert no.status_code == 422 and "MCC-1 supplies 1 row(s) in the Load List (M-204)" in no.json()["fields"]["i1.is_panel"]
    own = client.put("/api/eel", json={"items": [dict(items[0], is_panel=False), items[1]]})
    assert own.json()["fields"]["i1.is_panel"] == "DB-1 is supplied from it: change that first"
    gone = client.put("/api/eel", json={"items": [dict(items[1], supplied_from="primary")]})
    assert gone.status_code == 422 and "MCC-1 supplies 1 row(s)" in gone.json()["detail"]
    # ... and DB-1 (fed from MCC-1) can't feed MCC-1 back.
    loop = client.put("/api/eel", json={"items": [dict(items[0], supplied_from="eel/i2"), dict(items[1], is_panel=True)]})
    assert loop.status_code == 422 and "supply loop" in loop.json()["fields"]["i1.supplied_from"]
    assert (m204["supplied_from"], m204["supplied_from_by"]) == ("eel/i1", "auto")  # before the person chose it

    # What the list refers to can't be deleted from the other lists.
    r = client.put("/api/keylists/equipment-packages", json={"items": []})
    assert r.status_code == 422 and "PKG-010 (1 item)" in r.json()["detail"] and "PKG-020 (1 item)" in r.json()["detail"]
    assert "DB (1 item)" in client.put("/api/keylists/equipment-codes", json={"items": [
        {"id": "c1", "code": "MCC", "name": "MCC"}]}).json()["detail"]
    nodes = client.get("/api/keylists/plant-areas").json()["nodes"]
    r = client.put("/api/keylists/plant-areas", json={"nodes": [n for n in nodes if n["id"] != "a2"]})
    assert r.status_code == 422 and "200 (1 item)" in r.json()["detail"]
    assert client.put("/api/keylists/load-types", json={"items": []}).status_code == 422

    # Deleting an item leaves its Load List row, marked deleted. Survives a restart.
    assert client.put("/api/eel", json={"items": [items[0]]}).status_code == 200
    storage.configure(data_dir)
    ll = _ll()
    assert (ll["DB-1"]["status"], ll["DB-1"]["deleted_reason"]) == ("deleted", "Deleted from the Electrical Equipment List")
    assert [i["tag"] for i in client.get("/api/eel").json()["items"]] == ["MCC-1"]
    assert client.get("/api/keylists").json()["eel"] == {"items": 1}
    assert client.get("/api/dashboard").json()["counts"]["eel_items"] == 1


def test_clashes_stale_saves_and_log() -> None:
    assert client.put("/api/eel", json={"items": [_item("i1", "P-101")]}, headers=ANN).status_code == 200
    _mel()  # the import now has P-101 too
    client.get("/api/loadlist")
    assert client.get("/api/eel").json()["clashes"] == {"i1": ["Plant MEL"]}

    ann = client.get("/api/eel", headers=ANN).headers["ETag"]
    bob = client.get("/api/eel", headers=BOB).headers["ETag"]
    assert client.put("/api/eel", json={"items": [_item("i1", "MCC-9")]}, headers={**ANN, "If-Match": ann}).status_code == 200
    stale = client.put("/api/eel", json={"items": []}, headers={**BOB, "If-Match": bob})
    assert stale.status_code == 409 and stale.json()["changed_by"] == "ACME\\ann"
    log = client.get("/api/audit", params={"entity": "eel", "record_id": "eel"}).json()
    entries = log["entries"] if isinstance(log, dict) else log
    assert [e["label"] for e in entries] == ["Electrical Equipment List"] * 2
