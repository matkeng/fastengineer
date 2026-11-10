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
           {"field": "desc", "column": "Description"}, {"field": "load_type", "column": "Equipment Type"},
           {"field": "load_rating", "column": "Motor HP"}]


@pytest.fixture(autouse=True)
def data_dir(tmp_path: Path):
    storage.configure(tmp_path)
    yield tmp_path


def _import(name: str, target: str, file: str | bytes | None, key: str = "Equipment Tag", mapping=MAPPING) -> str:
    rid = client.post("/api/mel/recipes", json={"name": name, "target": target}).json()["id"]
    recipe = client.get(f"/api/mel/recipes/{rid}").json()["recipe"]
    assert client.put(f"/api/mel/recipes/{rid}", json=recipe | {"mapping": mapping}).status_code == 200
    if file is not None:
        _upload(rid, file, key)
    return rid


def _upload(rid: str, file: str | bytes, key: str = "Equipment Tag") -> None:
    data = (SAMPLES / file).read_bytes() if isinstance(file, str) else file
    res = client.post(f"/api/mel/recipes/{rid}/revisions/csv", params={"filename": "f.csv", "key": key}, content=data)
    assert res.status_code == 200, res.text


def _rows() -> dict[str, dict]:
    res = client.get("/api/loadlist")
    assert res.status_code == 200, res.text
    return {f"{r['source']}:{r['key']}": r for r in res.json()["rows"]}


def _alloc(rows: list[dict], headers: dict | None = None, **change):
    return client.put("/api/loadlist/allocations", headers=headers or {},
                      json={"rows": [{"recipe_id": r["recipe_id"], "key": r["key"]} for r in rows]} | change)


def test_load_list_combines_imports_fills_in_and_remembers(data_dir: Path) -> None:
    assert client.get("/api/loadlist").json()["rows"] == []
    areas = client.put("/api/keylists/plant-areas", json={"nodes": [
        {"id": "a1", "tag": "100", "description": "Feed area", "area_type": "Area"},
        {"id": "a2", "tag": "200", "description": "Mixing area", "area_type": "Area"},
        {"id": "b1", "parent_id": "a1", "tag": "B-1", "description": "Pump house", "area_type": "Building"},
    ]})
    assert areas.status_code == 200, areas.text
    types = client.put("/api/keylists/load-types", json={"items": [
        {"id": "t1", "code": "PUMP", "name": "Pump motor", "rating_unit": "kW", "voltage": 460, "phases": "AC-3-phase"},
        {"id": "t2", "code": "MIX", "name": "Mixer", "rating_unit": "kW", "voltage": 460, "phases": "AC-3-phase"},
    ]})
    assert types.status_code == 200, types.text

    mel = _import("Plant MEL", "MEL", "mel-sample.csv")
    eel = _import("Switchroom EEL", "EEL", b"Tag,Area,Description\nMCC-1,100,Motor control centre\nP-101,999,Same tag\n",
                  key="Tag", mapping=[{"field": "tag", "column": "Tag"}, {"field": "area", "column": "Area"},
                                      {"field": "desc", "column": "Description"}])
    _import("Instruments", "PIL", b"Tag\nFT-1\n", key="Tag", mapping=[{"field": "tag", "column": "Tag"}])
    _import("Empty MEL", "MEL", None)

    view = client.get("/api/loadlist").json()
    assert [(s["name"], s["target"], s["has_file"]) for s in view["sources"]] == [
        ("Empty MEL", "MEL", False), ("Switchroom EEL", "EEL", True), ("Plant MEL", "MEL", True)]
    assert view["fields"] == ["area", "tag", "desc", "load_rating", "load_type"]  # load-list order
    assert [a["label"] for a in view["plant_areas"]] == ["100 – Feed area", "B-1 – Pump house", "200 – Mixing area"]
    assert [a["depth"] for a in view["plant_areas"]] == [0, 1, 0]
    assert "Tag P-101 is in more than one row (Plant MEL, Switchroom EEL)." in view["warnings"]
    rows = {f"{r['source']}:{r['key']}": r for r in view["rows"]}
    assert not any(k.startswith("Instruments") for k in rows)  # only MEL and EEL imports
    p101, m204, mcc = rows["Plant MEL:P-101"], rows["Plant MEL:M-204"], rows["Switchroom EEL:MCC-1"]
    assert p101["values"]["load_rating"] == 40 and p101["status"] == "active"
    # Area text = a plant area's tag, and load type text = a load type's code (ignoring case): filled in.
    assert (p101["plant_area_id"], p101["plant_area_by"], p101["load_type_id"], p101["load_type_by"]) == ("a1", "auto", "t1", "auto")
    assert (m204["plant_area_id"], m204["load_type_id"]) == ("a2", None)  # "Mixer" is not a code
    assert (mcc["plant_area_id"], mcc["load_type_id"]) == ("a1", None)
    assert rows["Switchroom EEL:P-101"]["plant_area_id"] is None  # area 999 matches nothing

    # A person's choices, including "not allocated", are kept from now on.
    r = _alloc([m204], load_type_id="t2", plant_area_id="b1")
    assert r.status_code == 200, r.text
    assert (r.json()[0]["plant_area_by"], r.json()[0]["load_type_by"]) == ("user", "user")
    assert _alloc([rows["Plant MEL:P-102"]], load_type_id=None).status_code == 200
    assert _alloc([m204], plant_area_id="nope").status_code == 422
    assert _alloc([{"recipe_id": mel, "key": "nope"}], plant_area_id="a1").status_code == 404

    # New revision: F-301 leaves (kept, marked deleted, allocations kept), P-601 arrives.
    _upload(mel, "mel-sample-rev2.csv")
    # Automatic allocations follow the text: plant area "100" renamed to "100A".
    nodes = client.get("/api/keylists/plant-areas").json()["nodes"]
    client.put("/api/keylists/plant-areas", json={"nodes": [dict(n, tag="100A") if n["id"] == "a1" else n for n in nodes]})
    rows = _rows()
    f301 = rows["Plant MEL:F-301"]
    assert (f301["status"], f301["deleted_reason"]) == ("deleted", "Not in the latest file")
    assert rows["Plant MEL:P-601"]["status"] == "active"
    assert rows["Plant MEL:P-101"]["plant_area_id"] is None and rows["Plant MEL:P-101"]["load_type_id"] == "t1"
    assert (rows["Plant MEL:M-204"]["plant_area_id"], rows["Plant MEL:M-204"]["load_type_id"]) == ("b1", "t2")
    assert (rows["Plant MEL:P-102"]["load_type_id"], rows["Plant MEL:P-102"]["load_type_by"]) == (None, "user")

    # What a person allocated can't be deleted from Plant Areas / Load Types.
    nodes = client.get("/api/keylists/plant-areas").json()["nodes"]
    refused = client.put("/api/keylists/plant-areas", json={"nodes": [n for n in nodes if n["id"] != "b1"]})
    assert refused.status_code == 422 and "B-1 (1 row)" in refused.json()["detail"]
    loads = client.get("/api/keylists/load-types").json()["items"]
    refused = client.put("/api/keylists/load-types", json={"items": [t for t in loads if t["id"] != "t2"]})
    assert refused.status_code == 422 and "MIX (1 row)" in refused.json()["detail"]
    # PUMP is only filled in automatically: it can go, and its rows follow.
    assert client.put("/api/keylists/load-types", json={"items": [t for t in loads if t["id"] != "t1"]}).status_code == 200
    assert _rows()["Plant MEL:P-101"]["load_type_id"] is None

    # A deleted import's rows stay, marked deleted, with their allocations; they survive a restart.
    assert _alloc([rows["Switchroom EEL:MCC-1"]], plant_area_id="a2").status_code == 200
    client.delete(f"/api/mel/recipes/{eel}")
    storage.configure(data_dir)
    rows = _rows()
    assert (rows["Switchroom EEL:MCC-1"]["status"], rows["Switchroom EEL:MCC-1"]["deleted_reason"]) == (
        "deleted", "Its import was deleted")
    assert rows["Switchroom EEL:MCC-1"]["plant_area_id"] == "a2"
    active = sum(r["status"] == "active" for r in rows.values())
    assert client.get("/api/dashboard").json()["counts"]["load_list_rows"] == active
    assert client.get("/api/keylists").json()["load_list"]["rows"] == active

    log = client.get("/api/audit", params={"entity": "load_list_row"}).json()
    entries = log["entries"] if isinstance(log, dict) else log
    labels = [e["label"] for e in entries]
    assert "M-204" in labels and "P-102" in labels
    m = next(e for e in entries if e["label"] == "M-204")
    assert {c["path"]: c["new"] for c in m["changes"]} == {"plant area": "B-1 – Pump house", "load type": "MIX – Mixer"}
    auto = client.get("/api/audit", params={"entity": "load_list"}).json()
    assert (auto["entries"] if isinstance(auto, dict) else auto)


def test_bulk_allocation_and_stale_edits() -> None:
    client.put("/api/keylists/plant-areas", json={"nodes": [
        {"id": "a1", "tag": "X1", "description": "One", "area_type": "Area"},
        {"id": "a2", "tag": "X2", "description": "Two", "area_type": "Area"}]})
    _import("Plant MEL", "MEL", "mel-sample.csv")
    rows = list(_rows().values())
    r = _alloc(rows, plant_area_id="a1")
    assert r.status_code == 200 and {x["plant_area_id"] for x in r.json()} == {"a1"}

    # Ann and Bob both opened P-101; Ann saves first; Bob's change was made on the older copy.
    p101 = next(x for x in r.json() if x["key"] == "P-101")
    seen = {"X-Workbench-Base-Time": p101["updated_at"]}
    assert _alloc([p101], {**ANN, **seen}, plant_area_id="a2").status_code == 200
    stale = _alloc([p101], {**BOB, **seen}, plant_area_id=None)
    assert stale.status_code == 409 and stale.json()["changed_by"] == "ACME\\ann"
    assert _rows()["Plant MEL:P-101"]["plant_area_id"] == "a2"


def test_distribution_panels_and_supplied_from() -> None:
    _import("Plant MEL", "MEL", "mel-sample.csv", mapping=MAPPING + [{"field": "supplied_from", "manual": "mcc-1"}])
    _import("Switchroom EEL", "EEL", b"Tag,Load centre,Fed from\nMCC-1,yes,\nMCC-2,yes,MCC-1\nDB-1,no,\n", key="Tag",
            mapping=[{"field": "tag", "column": "Tag"}, {"field": "is_a_loadcentre", "column": "Load centre"},
                     {"field": "supplied_from", "column": "Fed from"}])
    rows = _rows()
    mcc1, mcc2, db1, p101 = (rows[k] for k in ("Switchroom EEL:MCC-1", "Switchroom EEL:MCC-2", "Switchroom EEL:DB-1",
                                              "Plant MEL:P-101"))
    ref = lambda r: f"{r['recipe_id']}/{r['key']}"  # noqa: E731
    # Filled in from the imports: panels from "Load centre", supply from a panel's tag.
    assert (mcc1["is_panel"], mcc1["is_panel_by"], mcc2["is_panel"], db1["is_panel"]) == (True, "auto", True, False)
    assert (mcc2["supplied_from"], mcc2["supplied_from_by"]) == (ref(mcc1), "auto")
    assert p101["supplied_from"] == ref(mcc1) and mcc1["supplied_from"] is None

    # A person's choices: primary supply, or a distribution panel of the list.
    assert _alloc([mcc1], supplied_from="primary").json()[0]["supplied_from"] == "primary"
    m204 = rows["Plant MEL:M-204"]
    assert _alloc([m204], supplied_from=ref(mcc2)).status_code == 200
    # The rules: a panel, not itself, no loops.
    bad = _alloc([m204], supplied_from=ref(db1))
    assert bad.status_code == 422 and "DB-1 is not an active distribution panel" in bad.json()["detail"]
    assert "itself" in _alloc([mcc2], supplied_from=ref(mcc2)).json()["detail"]
    loop = _alloc([mcc1], supplied_from=ref(mcc2))
    assert loop.status_code == 422 and "supply loop: MCC-1 → MCC-2" in loop.json()["detail"]
    assert _alloc([m204], supplied_from="nope/x").status_code == 422

    # A panel that supplies rows a person chose can't stop being one ...
    no = _alloc([mcc2], is_panel=False)
    assert no.status_code == 422 and "MCC-2 (1 row)" in no.json()["detail"]
    # ... but rows only filled in automatically just lose their supply.
    assert _alloc([mcc1], is_panel=False).status_code == 200
    rows = _rows()
    assert rows["Plant MEL:P-101"]["supplied_from"] is None and rows["Switchroom EEL:MCC-2"]["supplied_from"] is None
    assert rows["Switchroom EEL:MCC-1"]["is_panel"] is False  # a person's choice beats the import's "yes"
    # Making a row a panel, and supplying many rows from it at once.
    assert _alloc([db1], is_panel=True).status_code == 200
    mel_rows = [r for k, r in rows.items() if k.startswith("Plant MEL:") and r["status"] == "active"]
    r = _alloc(mel_rows, supplied_from=ref(db1))
    assert r.status_code == 200 and {x["supplied_from"] for x in r.json()} == {ref(db1)}

    log = client.get("/api/audit", params={"entity": "load_list_row", "record_id": ref(m204)}).json()
    entries = log["entries"] if isinstance(log, dict) else log
    assert [{c["path"]: c["new"] for c in e["changes"]} for e in entries] == [{"supplied from": "DB-1"}, {"supplied from": "MCC-2"}]
