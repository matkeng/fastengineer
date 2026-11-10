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


LOAD_URL = "/api/keylists/load-types"
LOADS = [
    {"id": "l2", "code": "VSD", "name": "Variable speed drive", "rating_unit": "kW", "voltage": "690",
     "phases": "AC-3-phase", "from_value": "2.50", "to_value": "75", "std_drg": "E-STD-012", "bucket_type": "B2",
     "load_type": "Motor", "field_options": "LCS", "multi_load": True, "load_qty": "2"},
    {"id": "l1", "code": "DOL", "name": "Direct on line", "rating_unit": "kW", "voltage": 415, "phases": "AC-3-phase"},
    {"id": "l3", "code": "INST", "name": "Instrument loop", "rating_unit": "Amps", "voltage": 24, "phases": "DC-mA"},
]


def test_load_types_save_rules_and_persistence(data_dir: Path) -> None:
    assert client.get(LOAD_URL).json() == {"items": [], "updated_at": None}
    ov = client.get("/api/keylists").json()
    assert ov["load_types"] == {"items": 0} and ov["rating_units"] == ["kW", "Amps"]
    assert ov["phases"] == ["AC-3-phase", "AC-3-phase+N", "AC-1-phase-LN", "AC-1-phase-LL", "DC", "DC-mA"]

    saved = client.put(LOAD_URL, json={"items": LOADS})
    assert saved.status_code == 200, saved.text
    vsd, dol, _ = saved.json()["items"]
    assert (vsd["id"], vsd["voltage"], vsd["from_value"], vsd["to_value"], vsd["multi_load"], vsd["load_qty"]) == (
        "l2", 690, "2.5", "75", True, 2)
    assert (dol["from_value"], dol["std_drg"], dol["multi_load"], dol["load_qty"]) == (None, "", False, None)

    bad = client.put(LOAD_URL, json={"items": LOADS + [
        {"id": "x1", "code": "dol", "name": "INSTRUMENT  loop", "rating_unit": "HP", "voltage": "415V", "phases": "AC",
         "from_value": "ten", "load_qty": 1.5},
        {"id": "x2", "code": "", "name": " ", "rating_unit": "kW", "voltage": "", "phases": "DC",
         "from_value": 10, "to_value": 5},
    ]})
    assert bad.status_code == 422
    assert set(bad.json()["fields"]) == {
        "x1.code", "x1.name", "x1.rating_unit", "x1.voltage", "x1.phases", "x1.from_value", "x1.load_qty",
        "x2.code", "x2.name", "x2.voltage", "x2.to_value"}

    # Refused saves kept nothing; the list survives a restart and the other lists are untouched.
    storage.configure(data_dir)
    assert [i["code"] for i in client.get(LOAD_URL).json()["items"]] == ["VSD", "DOL", "INST"]
    assert client.get("/api/keylists").json()["load_types"] == {"items": 3}
    assert client.get("/api/dashboard").json()["counts"]["load_types"] == 3
    assert client.get(URL).json()["nodes"] == [] and client.get(PKG_URL).json()["items"] == []


def test_load_types_change_log_and_conflicts() -> None:
    ann_tag = client.get(LOAD_URL, headers=ANN).headers["ETag"]
    bob_tag = client.get(LOAD_URL, headers=BOB).headers["ETag"]
    assert client.put(LOAD_URL, json={"items": LOADS}, headers={**ANN, "If-Match": ann_tag}).status_code == 200
    r = client.put(LOAD_URL, json={"items": LOADS[:1]}, headers={**BOB, "If-Match": bob_tag})
    assert r.status_code == 409 and r.json()["changed_by"] == "ACME\\ann"
    assert len(client.get(LOAD_URL).json()["items"]) == 3
    bob_tag = client.get(LOAD_URL, headers=BOB).headers["ETag"]
    changed = [dict(row, voltage=400) if row["id"] == "l1" else row for row in LOADS]
    assert client.put(LOAD_URL, json={"items": changed}, headers={**BOB, "If-Match": bob_tag}).status_code == 200

    log = client.get("/api/audit", params={"entity": "load_types", "record_id": "load-types"}).json()
    entries = log["entries"] if isinstance(log, dict) else log
    assert [e["user"] for e in entries] == ["ACME\\bob", "ACME\\ann"]
    assert all(e["label"] == "Load Types" for e in entries)
    assert any(c["path"].endswith("items[Direct on line].voltage") and c["new"] == 400 for c in entries[0]["changes"])


def _pdf(pages: int = 1) -> bytes:
    import io

    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument.new()
    for _ in range(pages):
        doc.new_page(200, 200)
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


def test_load_type_pdf_attach_view_replace_remove(data_dir: Path) -> None:
    client.put(LOAD_URL, json={"items": LOADS})
    url = f"{LOAD_URL}/l1/pdf"
    assert client.get(url).status_code == 404  # nothing attached yet

    # Only a real PDF, and only to a load type that exists.
    bad = client.put(url, params={"filename": "notes.pdf"}, content=b"not a pdf")
    assert bad.status_code == 400 and "PDF" in bad.json()["detail"]
    assert client.put(f"{LOAD_URL}/nope/pdf", params={"filename": "a.pdf"}, content=_pdf()).status_code == 404
    assert client.put(f"{LOAD_URL}/../pdf", params={"filename": "a.pdf"}, content=_pdf()).status_code == 404

    data = _pdf(2)
    r = client.put(url, params={"filename": "C:\\drawings\\DOL starter.pdf"}, content=data)
    assert r.status_code == 200, r.text
    dol = next(i for i in r.json()["items"] if i["id"] == "l1")
    assert (dol["pdf"]["file_name"], dol["pdf"]["size"], dol["pdf"]["pages"]) == ("DOL starter.pdf", len(data), 2)
    assert next(i for i in r.json()["items"] if i["id"] == "l2")["pdf"] is None
    got = client.get(url)
    assert got.status_code == 200 and got.content == data
    assert got.headers["content-type"] == "application/pdf" and got.headers["content-disposition"].startswith("inline")

    # Saving the rows keeps the PDF, and a client can't set or clear it through a row.
    rows = [dict(row, voltage=400) if row["id"] == "l1" else row for row in LOADS]
    rows[0] = dict(rows[0], pdf={"file_name": "fake.pdf", "size": 1, "pages": 1, "uploaded_at": "2026-01-01T00:00:00Z"})
    saved = client.put(LOAD_URL, json={"items": rows}).json()["items"]
    assert [(i["id"], i["pdf"] and i["pdf"]["file_name"]) for i in saved] == [
        ("l2", None), ("l1", "DOL starter.pdf"), ("l3", None)]

    # Replacing, then removing; each is in the change log. The file goes with it.
    storage.configure(data_dir)
    assert client.put(url, params={"filename": "rev B.pdf"}, content=_pdf(3)).json()["items"][1]["pdf"]["pages"] == 3
    assert client.get(url).content != data
    assert client.delete(url).json()["items"][1]["pdf"] is None
    assert client.get(url).status_code == 404
    log = client.get("/api/audit", params={"entity": "load_types", "record_id": "load-types"}).json()
    entries = log["entries"] if isinstance(log, dict) else log
    notes = [c["new"] for e in entries for c in e["changes"] if c["path"] == "(note)"]
    assert notes[:3] == ["PDF removed", f"PDF attached: rev B.pdf ({len(_pdf(3)):,} bytes)",
                         f"PDF attached: DOL starter.pdf ({len(data):,} bytes)"]

    # Deleting a load type deletes its PDF.
    client.put(url, params={"filename": "again.pdf"}, content=data)
    files = list((data_dir).rglob("l1.pdf"))
    assert len(files) == 1
    assert client.put(LOAD_URL, json={"items": LOADS[:1]}).status_code == 200
    assert not files[0].exists()
    assert client.delete(url).status_code == 404


@pytest.mark.parametrize("list_id, extra, entity", [
    ("equipment-codes", {"disciplines": ["M", "E"]}, "equipment_codes"),
    ("instrument-codes", {"plc_code": "AI"}, "instrument_codes"),
])
def test_code_lists_save_rules_conflicts_and_log(data_dir: Path, list_id: str, extra: dict, entity: str) -> None:
    url = f"/api/keylists/{list_id}"
    assert client.get(url).json() == {"items": [], "updated_at": None}
    ov = client.get("/api/keylists").json()
    assert ov[entity] == {"items": 0} and ov["disciplines"][0] == {"code": "E", "name": "Electrical"}

    rows = [{"id": "c1", "code": "A1", "name": "First", **extra}, {"id": "c2", "code": "B2", "name": "Second", "description": "x"}]
    ann_tag = client.get(url, headers=ANN).headers["ETag"]
    bob_tag = client.get(url, headers=BOB).headers["ETag"]
    saved = client.put(url, json={"items": rows}, headers={**ANN, "If-Match": ann_tag})
    assert saved.status_code == 200, saved.text
    first = saved.json()["items"][0]
    assert first == {"id": "c1", "code": "A1", "name": "First", "description": "",
                     **({"disciplines": ["E", "M"]} if "disciplines" in extra else {"plc_code": "AI"})}

    bad = client.put(url, json={"items": rows + [{"id": "c3", "code": "a1", "name": " second"}, {"id": "c4", "code": "", "name": ""}]})
    assert bad.status_code == 422 and set(bad.json()["fields"]) == {"c3.code", "c3.name", "c4.code", "c4.name"}
    stale = client.put(url, json={"items": rows[:1]}, headers={**BOB, "If-Match": bob_tag})
    assert stale.status_code == 409 and stale.json()["changed_by"] == "ACME\\ann"

    storage.configure(data_dir)
    assert [i["code"] for i in client.get(url).json()["items"]] == ["A1", "B2"]
    assert client.get("/api/keylists").json()[entity] == {"items": 2}
    assert client.get("/api/dashboard").json()["counts"][entity] == 2
    assert client.get(LOAD_URL).json()["items"] == [] and client.get(URL).json()["nodes"] == []
    log = client.get("/api/audit", params={"entity": entity, "record_id": list_id}).json()
    entries = log["entries"] if isinstance(log, dict) else log
    assert [e["user"] for e in entries] == ["ACME\\ann"]


def test_unknown_discipline_is_a_field_error() -> None:
    r = client.put("/api/keylists/equipment-codes", json={"items": [{"id": "c1", "code": "A", "name": "A", "disciplines": ["Q"]}]})
    assert r.status_code == 422 and r.json()["fields"] == {"c1.disciplines": "Not a discipline: Q"}
