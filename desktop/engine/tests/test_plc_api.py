# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from workbench_core.generators.hardware import Card, Hardware, Panel, Rack
from workbench_desktop import storage
from workbench_desktop.app import app

SAMPLE = Path(__file__).resolve().parents[3] / "samples" / "generator-sample.xlsx"
client = TestClient(app)
ANN = {"X-Workbench-User": "ACME\\ann", "X-Workbench-Machine": "PC-01"}
BOB = {"X-Workbench-User": "ACME\\bob", "X-Workbench-Machine": "PC-02"}


@pytest.fixture(autouse=True)
def data_dir(tmp_path: Path):
    storage.configure(tmp_path)
    client.put("/api/keylists/plant-areas", json={"nodes": [
        {"id": "a1", "tag": "100", "description": "Feed area", "area_type": "Area"},
        {"id": "a2", "tag": "200", "description": "Mixing area", "area_type": "Area"}]})
    yield tmp_path


def _card(t: str, **more) -> dict:
    return {"card_type_id": t} | more


def _plc(**rack) -> dict:
    return {"systems": [{"id": "s1", "tag": "PLC-1", "description": "Main PLC", "manufacturer": "ACME", "model": "X-1",
                         "racks": [{"id": "r1", "tag": "PLC-1-RK1", "plant_area_id": "a1", "rack_type_id": "rack",
                                    "cards": [_card("net", id="c0"), _card("di16", id="c1"), None, _card("ai8", id="c3")]} | rack]}]}


def test_save_points_rules_and_reload(data_dir: Path) -> None:
    v = client.get("/api/plc").json()
    assert v["plc"]["systems"] == [] and [a["label"] for a in v["plant_areas"]] == ["100 – Feed area", "200 – Mixing area"]
    r = client.put("/api/plc", json=_plc())
    assert r.status_code == 200, r.text
    cards = r.json()["plc"]["systems"][0]["racks"][0]["cards"]
    assert [None if c is None else len(c["points"]) for c in cards] == [0, 16, None, 8]
    assert r.json()["summary"]["cards"] == 3 and r.json()["findings"] == []

    # Point tags, then the rules.
    plc = r.json()["plc"]
    plc["systems"][0]["racks"][0]["cards"][1]["points"][4] |= {"tag": "XS-104", "description": "Pump running"}
    assert client.put("/api/plc", json=plc).status_code == 200
    bad = dict(plc, systems=plc["systems"] + [{"tag": "plc-1", "racks": [
        {"tag": "plc-1-rk1", "rack_type_id": "nope", "cards": [_card("di8", tag="PLC-1-RK1-S2")]}]}])
    res = client.put("/api/plc", json=bad)
    assert res.status_code == 422
    assert len(res.json()["fields"]) == 4  # system tag, rack tag, rack type, card name
    shrink = client.put("/api/plc", json={"systems": [dict(plc["systems"][0], racks=[dict(
        plc["systems"][0]["racks"][0], cards=[cards[0], dict(plc["systems"][0]["racks"][0]["cards"][1], card_type_id="di8")])])]})
    # di16 -> di8 keeps channels 0..7, so the tagged channel 4 stays with its tag.
    di = shrink.json()["plc"]["systems"][0]["racks"][0]["cards"][1]
    assert shrink.status_code == 200 and len(di["points"]) == 8 and di["points"][4]["tag"] == "XS-104"
    # A draft check reports without saving.
    chk = client.post("/api/plc/check", json=_plc(plant_area_id=None, cards=[_card("di8")])).json()
    assert [f["code"] for f in chk["findings"]] == ["P1", "P2"] and chk["errors"] == {}

    storage.configure(data_dir)
    saved = client.get("/api/plc").json()["plc"]["systems"][0]
    assert (saved["manufacturer"], saved["racks"][0]["cards"][1]["points"][4]["tag"]) == ("ACME", "XS-104")
    assert client.get("/api/keylists").json()["plc"] == {"systems": 1, "racks": 1, "cards": 2}
    counts = client.get("/api/dashboard").json()["counts"]
    assert (counts["plc_panels"], counts["plc_cards"]) == (1, 2)

    # A plant area with racks can't be deleted.
    nodes = client.get("/api/keylists/plant-areas").json()["nodes"]
    r = client.put("/api/keylists/plant-areas", json={"nodes": [n for n in nodes if n["id"] != "a1"]})
    assert r.status_code == 422 and "100 (1 rack)" in r.json()["detail"]


def test_tagged_channels_cant_be_dropped() -> None:
    plc = client.put("/api/plc", json=_plc()).json()["plc"]
    rack = plc["systems"][0]["racks"][0]
    rack["cards"][1]["points"][12]["tag"] = "XS-112"
    rack["cards"][1]["card_type_id"] = "di8"
    res = client.put("/api/plc", json=plc)
    assert res.status_code == 422 and "channel(s) 12 have a tag" in res.json()["fields"]["c1.card_type_id"]


def test_catalogue_guard_stale_save_and_log() -> None:
    cat = client.get("/api/plc/catalogue").json()
    assert len(cat["card_types"]) == 21 and cat["rack_types"][0]["id"] == "rack"
    client.put("/api/plc", json=_plc())
    less = {**cat, "card_types": [t for t in cat["card_types"] if t["id"] != "di16"]}
    r = client.put("/api/plc/catalogue", json=less)
    assert r.status_code == 422 and "can't be removed" in r.json()["detail"]
    unused = {**cat, "card_types": [t for t in cat["card_types"] if t["id"] != "rtd32"]}
    assert client.put("/api/plc/catalogue", json=unused).status_code == 200
    assert "rtd32" in {t["id"] for t in client.post("/api/plc/catalogue/defaults").json()["card_types"]}

    ann = client.get("/api/plc", headers=ANN).headers["ETag"]
    bob = client.get("/api/plc", headers=BOB).headers["ETag"]
    assert client.put("/api/plc", json=_plc(tag="RK-A"), headers={**ANN, "If-Match": ann}).status_code == 200
    stale = client.put("/api/plc", json=_plc(tag="RK-B"), headers={**BOB, "If-Match": bob})
    assert stale.status_code == 409 and stale.json()["changed_by"] == "ACME\\ann"
    log = client.get("/api/audit", params={"entity": "plc", "record_id": "plc"}).json()
    entries = log["entries"] if isinstance(log, dict) else log
    assert entries[0]["label"] == "PLC List"


def test_export_and_import(tmp_path: Path) -> None:
    plc = client.put("/api/plc", json=_plc()).json()["plc"]
    plc["systems"][0]["racks"][0]["cards"][3]["points"][0]["tag"] = "FT-100"
    client.put("/api/plc", json=plc)
    res = client.post("/api/plc/export", json={})
    wb = load_workbook(io.BytesIO(res.content))
    assert wb.sheetnames == ["PLC cards", "IO points", "Card types", "Rack types"]
    assert [c.value for c in wb["PLC cards"][1]][15:] == ["Rack tag", "Plant area", "Manufacturer", "Model"]
    assert [c.value for c in wb["PLC cards"][2]][15:17] == ["PLC-1-RK1", "100"]
    io_rows = [[c.value for c in row] for row in wb["IO points"].iter_rows(min_row=2)]
    assert ["PLC-1-RK1", 4, "PLC-1-RK1-S4", 0, "AI", "FT-100", None, None] in io_rows

    # Edit the file and import it: preview first, then apply.
    wb["PLC cards"]["Q2"] = "200"  # plant area of the rack
    wb["IO points"].append(["PLC-1-RK1", 2, None, 5, None, "XS-105", "Valve open", "yes"])
    buf = io.BytesIO()
    wb.save(buf)
    pv = client.post("/api/plc/import", params={"filename": "PLC List.xlsx"}, content=buf.getvalue()).json()
    assert (pv["systems"], pv["racks"], pv["cards"], pv["tagged_points"], pv["applied"]) == (1, 1, 3, 2, False)
    assert client.get("/api/plc").json()["plc"]["systems"][0]["racks"][0]["plant_area_id"] == "a1"
    done = client.post("/api/plc/import", params={"filename": "PLC List.xlsx", "apply": True}, content=buf.getvalue()).json()
    assert done["applied"]
    rack = client.get("/api/plc").json()["plc"]["systems"][0]["racks"][0]
    assert rack["plant_area_id"] == "a2" and rack["cards"][1]["points"][5] == {
        "channel": 5, "tag": "XS-105", "description": "Valve open", "spare": True}
    assert client.post("/api/plc/import", params={"filename": "x.xlsx"}, content=b"nope").status_code == 400
    out = client.post("/api/plc/export", json={"path": str(tmp_path / "plc")}).json()
    assert out["path"].endswith("plc.xlsx") and (tmp_path / "plc.xlsx").exists()


def test_generators_registers_are_moved_once() -> None:
    rid = client.post("/api/generators/import", params={"filename": SAMPLE.name}, content=SAMPLE.read_bytes()).json()["record"]["id"]
    hw = Hardware(panels=[Panel(tag="PCC-01", location="200", racks=[Rack(number=1, rack_type_id="rack", cards=[
        Card(card_type_id="net"), Card(card_type_id="di16", tag="DI-A")])])])
    st = storage.get_store()
    with st._lock, st._db:  # a register saved before the PLC List existed
        st._db.execute("INSERT INTO gen_hardware VALUES (?, ?, ?)", (rid, hw.model_dump_json(), "2026-01-01T00:00:00Z"))
    v = client.get("/api/plc").json()
    s = v["plc"]["systems"][0]
    assert (s["tag"], s["racks"][0]["tag"], s["racks"][0]["plant_area_id"]) == ("PCC-01", "PCC-01-R1", "a2")
    assert [c["tag"] for c in s["racks"][0]["cards"]] == ["", "DI-A"] and len(s["racks"][0]["cards"][1]["points"]) == 16
    log = client.get("/api/audit", params={"entity": "plc", "record_id": "plc"}).json()
    entries = log["entries"] if isinstance(log, dict) else log
    assert any(c["new"] == "Moved from the generators' PLC hardware registers" for c in entries[0]["changes"])
    # Only once: emptied, it stays empty.
    assert client.put("/api/plc", json={"systems": []}).status_code == 200
    assert client.get("/api/plc").json()["plc"]["systems"] == []
    assert client.get(f"/api/generators/{rid}/hardware").json()["summary"]["cards"] == 0
