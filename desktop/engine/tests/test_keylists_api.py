# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from workbench_desktop import storage
from workbench_desktop.app import app

client = TestClient(app)
URL = "/api/keylists/plant-areas"
ANN = {"X-Workbench-User": "ACME\\ann", "X-Workbench-Machine": "PC-01"}
BOB = {"X-Workbench-User": "ACME\\bob", "X-Workbench-Machine": "PC-02"}

NODES = [
    {"id": "b1", "parent_id": "a1", "wbs": "1.1", "tag": "B-10", "description": "Substation", "area_type": "Building"},
    {"id": "a1", "parent_id": None, "wbs": "1", "tag": "A-100", "description": "Process area", "area_type": "Area"},
    {"id": "r1", "parent_id": "b1", "tag": "R-101", "description": "Control room", "area_type": "Room"},
    {"id": "p1", "parent_id": "r1", "tag": "LCP-01", "description": "Local control panel", "area_type": "Panel"},
]


@pytest.fixture(autouse=True)
def data_dir(tmp_path: Path):
    storage.configure(tmp_path)
    yield tmp_path


def test_plant_areas_save_rules_and_persistence(data_dir: Path) -> None:
    # Every project has the list from the start, empty.
    assert client.get(URL).json() == {"nodes": [], "updated_at": None}
    ov = client.get("/api/keylists").json()
    assert ov["plant_areas"] == {"items": 0, "depth": 0}
    assert ov["area_types"] == ["WBS", "Area", "Building", "Room", "Panel"]

    saved = client.put(URL, json={"nodes": NODES})
    assert saved.status_code == 200, saved.text
    assert [n["id"] for n in saved.json()["nodes"]] == ["a1", "b1", "r1", "p1"]  # parents first
    assert saved.json()["nodes"][2]["wbs"] == ""

    # Tag and description: required, unique in the whole list. WBS: unique when filled.
    bad = client.put(URL, json={"nodes": NODES + [
        {"id": "x1", "parent_id": None, "wbs": "1.1", "tag": "a-100", "description": "CONTROL ROOM", "area_type": "WBS"},
        {"id": "x2", "parent_id": None, "tag": "", "description": " ", "area_type": "WBS"},
    ]})
    assert bad.status_code == 422
    assert set(bad.json()["fields"]) == {"x1.tag", "x1.description", "x1.wbs", "x2.tag", "x2.description"}
    # Only the listed area types.
    assert client.put(URL, json={"nodes": [{"tag": "S", "description": "Shed", "area_type": "Shed"}]}).status_code == 422
    assert client.put(URL, json={"nodes": [{"tag": "S", "description": "Shed"}]}).status_code == 422

    # Nothing of the refused saves was kept; the list survives a restart.
    storage.configure(data_dir)
    assert [n["tag"] for n in client.get(URL).json()["nodes"]] == ["A-100", "B-10", "R-101", "LCP-01"]
    assert client.get("/api/keylists").json()["plant_areas"] == {"items": 4, "depth": 4}
    assert client.get("/api/dashboard").json()["counts"]["plant_areas"] == 4


def test_plant_areas_change_log_and_conflicts() -> None:
    ann_tag = client.get(URL, headers=ANN).headers["ETag"]
    bob_tag = client.get(URL, headers=BOB).headers["ETag"]
    r = client.put(URL, json={"nodes": NODES}, headers={**ANN, "If-Match": ann_tag})
    assert r.status_code == 200
    # Bob still has the empty list: his save is refused, not written over Ann's.
    r = client.put(URL, json={"nodes": NODES[1:2]}, headers={**BOB, "If-Match": bob_tag})
    assert r.status_code == 409 and r.json()["changed_by"] == "ACME\\ann"
    assert len(client.get(URL).json()["nodes"]) == 4
    bob_tag = client.get(URL, headers=BOB).headers["ETag"]
    renamed = [dict(n, description="Main substation") if n["id"] == "b1" else n for n in NODES]
    assert client.put(URL, json={"nodes": renamed}, headers={**BOB, "If-Match": bob_tag}).status_code == 200

    log = client.get("/api/audit", params={"entity": "plant_areas", "record_id": "plant-areas"}).json()
    entries = log["entries"] if isinstance(log, dict) else log
    assert [e["user"] for e in entries] == ["ACME\\bob", "ACME\\ann"]
    assert all(e["label"] == "Plant Areas" for e in entries)
    assert any(c["new"] == "Main substation" for c in entries[0]["changes"])


PKG_URL = "/api/keylists/equipment-packages"
PACKAGES = [
    {"id": "k2", "number": "PKG-020", "description": "Control valves", "vendor": "Acme", "package_type": "Valves"},
    {"id": "k1", "number": "PKG-010", "description": "Feed pumps", "vendor": "Acme", "package_type": "Large Mech"},
    {"id": "k3", "number": "PKG-030", "description": "Site installation", "package_type": "Installer"},
]


def test_equipment_packages_save_rules_and_persistence(data_dir: Path) -> None:
    assert client.get(PKG_URL).json() == {"items": [], "types": [], "updated_at": None}
    ov = client.get("/api/keylists").json()
    assert ov["equipment_packages"] == {"items": 0, "types": 0}
    assert ov["package_types"] == ["Vendor", "Client", "SWR Supplier", "Valves", "Instrumentation", "Large Mech",
                                   "Installer", "Other"]

    saved = client.put(PKG_URL, json={"items": PACKAGES})
    assert saved.status_code == 200, saved.text
    assert [i["id"] for i in saved.json()["items"]] == ["k2", "k1", "k3"]  # the order given
    assert saved.json()["items"][2]["vendor"] == ""

    bad = client.put(PKG_URL, json={"items": PACKAGES + [
        {"id": "x1", "number": "pkg-010", "description": "CONTROL  valves", "vendor": "Acme", "package_type": "Other"},
        {"id": "x2", "number": "", "description": " ", "package_type": "Client"},
    ]})
    assert bad.status_code == 422
    assert set(bad.json()["fields"]) == {"x1.number", "x1.description", "x2.number", "x2.description"}
    one = {"number": "P", "description": "Pipes"}
    assert client.put(PKG_URL, json={"items": [one | {"package_type": "Piping"}]}).status_code == 422
    assert client.put(PKG_URL, json={"items": [one]}).status_code == 422

    # Refused saves kept nothing; the list survives a restart and is separate from Plant Areas.
    storage.configure(data_dir)
    assert [i["number"] for i in client.get(PKG_URL).json()["items"]] == ["PKG-020", "PKG-010", "PKG-030"]
    assert client.get("/api/keylists").json()["equipment_packages"] == {"items": 3, "types": 0}
    assert client.get("/api/dashboard").json()["counts"]["equipment_packages"] == 3
    assert client.get(URL).json()["nodes"] == []


def test_equipment_packages_change_log_and_conflicts() -> None:
    ann_tag = client.get(PKG_URL, headers=ANN).headers["ETag"]
    bob_tag = client.get(PKG_URL, headers=BOB).headers["ETag"]
    assert client.put(PKG_URL, json={"items": PACKAGES}, headers={**ANN, "If-Match": ann_tag}).status_code == 200
    r = client.put(PKG_URL, json={"items": PACKAGES[:1]}, headers={**BOB, "If-Match": bob_tag})
    assert r.status_code == 409 and r.json()["changed_by"] == "ACME\\ann"
    assert len(client.get(PKG_URL).json()["items"]) == 3
    bob_tag = client.get(PKG_URL, headers=BOB).headers["ETag"]
    changed = [dict(p, vendor="Globex") if p["id"] == "k1" else p for p in PACKAGES]
    assert client.put(PKG_URL, json={"items": changed}, headers={**BOB, "If-Match": bob_tag}).status_code == 200

    log = client.get("/api/audit", params={"entity": "equipment_packages", "record_id": "equipment-packages"}).json()
    entries = log["entries"] if isinstance(log, dict) else log
    assert [e["user"] for e in entries] == ["ACME\\bob", "ACME\\ann"]
    assert all(e["label"] == "Equipment Packages" for e in entries)
    assert any(c["new"] == "Globex" for c in entries[0]["changes"])


TYPES = [
    {"id": "t3", "package_id": "k2", "name": "Globe valve", "description": "Throttling"},
    {"id": "t1", "package_id": "k1", "name": "Centrifugal pump"},
    {"id": "t2", "package_id": "k1", "name": "Dosing pump"},
]


def test_equipment_types_under_packages(data_dir: Path) -> None:
    saved = client.put(PKG_URL, json={"items": PACKAGES, "types": TYPES})
    assert saved.status_code == 200, saved.text
    # Grouped by package, in package order (k2, k1, k3).
    assert [(t["id"], t["package_id"]) for t in saved.json()["types"]] == [("t3", "k2"), ("t1", "k1"), ("t2", "k1")]
    assert saved.json()["types"][1]["description"] == ""

    bad = client.put(PKG_URL, json={"items": PACKAGES, "types": TYPES + [
        {"id": "x1", "package_id": "k3", "name": "globe  VALVE"},     # used in another package
        {"id": "x2", "package_id": "k3", "name": " "},
        {"id": "x3", "package_id": "nope", "name": "Motor"},
    ]})
    assert bad.status_code == 422
    assert set(bad.json()["fields"]) == {"x1.name", "x2.name", "x3.package"}
    assert client.put(PKG_URL, json={"items": PACKAGES, "types": [{"name": "No package"}]}).status_code == 422

    # A package with types can't be deleted ...
    gone = client.put(PKG_URL, json={"items": PACKAGES[1:], "types": TYPES})
    assert gone.status_code == 422 and gone.json()["fields"] == {"t3.package": "Its package is not in the list"}
    # ... also not by a save that doesn't mention the types (they stay as they are).
    assert client.put(PKG_URL, json={"items": PACKAGES[1:]}).status_code == 422
    renamed = [dict(p, vendor="Globex") for p in PACKAGES]
    kept = client.put(PKG_URL, json={"items": renamed})
    assert kept.status_code == 200 and len(kept.json()["types"]) == 3
    # ... until its types are moved to another package (or deleted).
    moved = [dict(t, package_id="k3") if t["id"] == "t3" else t for t in TYPES]
    ok = client.put(PKG_URL, json={"items": renamed[1:], "types": moved})
    assert ok.status_code == 200, ok.text
    assert [(t["id"], t["package_id"]) for t in ok.json()["types"]] == [("t1", "k1"), ("t2", "k1"), ("t3", "k3")]

    storage.configure(data_dir)
    assert [t["name"] for t in client.get(PKG_URL).json()["types"]] == ["Centrifugal pump", "Dosing pump", "Globe valve"]
    assert client.get("/api/keylists").json()["equipment_packages"] == {"items": 2, "types": 3}
    counts = client.get("/api/dashboard").json()["counts"]
    assert (counts["equipment_packages"], counts["equipment_types"]) == (2, 3)
    log = client.get("/api/audit", params={"entity": "equipment_packages", "record_id": "equipment-packages"}).json()
    entries = log["entries"] if isinstance(log, dict) else log
    assert any("types[Globe valve]" in c["path"] for c in entries[0]["changes"])
