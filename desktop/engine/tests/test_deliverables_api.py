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

SAMPLE = Path(__file__).resolve().parents[3] / "samples" / "generator-sample.xlsx"
client = TestClient(app)
API = "/api/deliverables"
ANN = {"X-Workbench-User": "ACME\\ann", "X-Workbench-Machine": "PC-01"}


@pytest.fixture(autouse=True)
def data_dir(tmp_path: Path):
    storage.configure(tmp_path)
    yield tmp_path


def _generator() -> str:
    res = client.post("/api/generators/import", params={"filename": SAMPLE.name}, content=SAMPLE.read_bytes())
    return res.json()["record"]["id"]


def _build(rid: str) -> dict:
    res = client.post(f"/api/generators/{rid}/builds", json={})
    assert res.status_code == 200, res.text
    return res.json()


def _rename_run(rid: str, row: int, text: str) -> None:
    rec = client.get(f"/api/generators/{rid}").json()
    rec["generator"]["runsheet"]["rows"][row]["values"][5] = text
    assert client.put(f"/api/generators/{rid}", json={"name": rec["name"], "generator": rec["generator"]}).status_code == 200


def _new(rid: str, **more) -> dict:
    body = {"type": "Cable Schedule", "name": "Lighting cable schedule", "doc_number": "E-SCH-001",
            "doc_title": "Lighting Cable Schedule", "generator_id": rid} | more
    res = client.post(API, json=body)
    assert res.status_code == 200, res.text
    return res.json()


def test_deliverables_and_their_rules() -> None:
    rid = _generator()
    ov = client.get(API).json()
    assert ov["types"] == ["Cable Schedule", "Instrument List", "PLC I/O List", "Equipment List", "Load List",
                           "Distribution Panel"]
    assert ov["deliverables"] == [] and "Cable Number" in ov["generators"][0]["columns"]
    a = _new(rid)
    b = _new(rid, name="Lighting cables, 100 area", doc_number="E-SCH-002", filter_column="from", filter_values=["100-LB01"])
    _new(rid, type="Load List", name="Loads")
    bad = client.post(API, json={"type": "Cable Schedule", "name": " lighting CABLE schedule", "generator_id": "nope",
                                 "filter_column": "Zone"})
    assert bad.status_code == 422 and set(bad.json()["fields"]) == {"name", "generator_id", "filter_values"}
    assert client.post(API, json={"type": "Drawing", "name": "x", "generator_id": rid}).status_code == 422
    assert client.put(f"{API}/{b['id']}", json=dict(b, filter_column="Zone")).json()["fields"] == {
        "filter_column": "Not a column of the generator's output"}
    names = [(s["deliverable"]["type"], s["deliverable"]["name"]) for s in client.get(API).json()["deliverables"]]
    assert names == [("Cable Schedule", "Lighting cable schedule"), ("Cable Schedule", "Lighting cables, 100 area"),
                     ("Load List", "Loads")]
    # Nothing built yet: nothing to issue.
    d = client.get(f"{API}/{a['id']}").json()
    assert d["current"]["build"] is None and "has not been built" in d["current"]["problem"] and d["current"]["next_letter"] == "A"
    assert client.post(f"{API}/{a['id']}/revisions", json={}).status_code == 422
    # A generator that feeds deliverables can't be deleted; an unissued deliverable can.
    assert "feeds the deliverable(s)" in client.delete(f"/api/generators/{rid}").json()["detail"]
    assert client.delete(f"{API}/{b['id']}").status_code == 200


def test_issue_compare_withdraw_and_export(data_dir: Path, tmp_path: Path) -> None:
    rid = _generator()
    full = _new(rid)
    part = _new(rid, name="100 area only", doc_number="", doc_title="", filter_column="From", filter_values=["100-lb01"])
    b1 = _build(rid)
    cur = client.get(f"{API}/{full['id']}", params={"rows": True}).json()["current"]
    assert (cur["rows"], cur["next_letter"], cur["changes"], cur["stale"]) == (12, "A", None, False)
    assert len(cur["result"]["rows"]) == 19  # with the separator rows

    rev_a = client.post(f"{API}/{full['id']}/revisions", json={"description": "For review"}, headers=ANN).json()
    assert (rev_a["letter"], rev_a["issued_by"], rev_a["rows"], rev_a["build_seq"], rev_a["added"]) == ("A", "ACME\\ann", 12, 1, None)
    pa = client.post(f"{API}/{part['id']}/revisions", json={}).json()
    assert pa["letter"] == "A" and 0 < pa["rows"] < 12  # the filter is applied (each deliverable has its own letters)

    # The generator moves on: unbuilt edits are flagged; after a build the pending changes show.
    _rename_run(rid, 0, "CHANGED DESTINATION")
    assert client.get(f"{API}/{full['id']}").json()["current"]["stale"] is True
    _build(rid)
    cur = client.get(f"{API}/{full['id']}").json()["current"]
    assert (cur["stale"], cur["next_letter"], cur["changes"]["changed"], cur["changes"]["added"]) == (False, "B", 2, 0)
    assert cur["result"] is None  # rows only when asked for

    rev_b = client.post(f"{API}/{full['id']}/revisions", json={"description": "IFC"}).json()
    assert (rev_b["letter"], rev_b["build_seq"], rev_b["changed"], rev_b["added"], rev_b["removed"]) == ("B", 2, 2, 0, 0)
    b = client.get(f"{API}/revisions/{rev_b['id']}").json()
    cells = {c["column"]: (c["old"], c["new"]) for e in b["changes"]["entries"] for c in e["cells"]}
    assert cells["To Location"][1].startswith("CHANGED DESTINATION") and b["doc_number"] == "E-SCH-001"
    # Rev A is frozen: later builds, deleting its build, and edits to the deliverable don't touch it.
    client.delete(f"/api/generators/builds/{b1['id']}")
    client.put(f"{API}/{full['id']}", json=dict(full, doc_number="E-SCH-099", filter_column="From", filter_values=["nothing"]))
    a = client.get(f"{API}/revisions/{rev_a['id']}").json()
    assert a["doc_number"] == "E-SCH-001" and sum(1 for r in a["result"]["rows"] if r["run_row_id"]) == 12
    assert not any("CHANGED DESTINATION" in str(c) for r in a["result"]["rows"] for c in r["cells"])
    client.put(f"{API}/{full['id']}", json=full)

    # Only the description can be amended.
    info = client.put(f"{API}/revisions/{rev_b['id']}", json={"description": "Issued for construction"}).json()
    assert info["description"] == "Issued for construction" and info["letter"] == "B" and info["issued_at"] == rev_b["issued_at"]
    # Only the latest revision can be withdrawn, with a reason; its letter is used again.
    no = client.post(f"{API}/revisions/{rev_a['id']}/withdraw", json={"reason": "wrong"})
    assert no.status_code == 422 and "Only the latest revision (Rev B)" in no.json()["detail"]
    assert client.post(f"{API}/revisions/{rev_b['id']}/withdraw", json={"reason": " "}).status_code == 422
    assert client.post(f"{API}/revisions/{rev_b['id']}/withdraw", json={"reason": "Issued too early"}).json()["letter"] == "B"
    assert client.get(f"{API}/revisions/{rev_b['id']}").status_code == 404
    again = client.post(f"{API}/{full['id']}/revisions", json={"description": "IFC"}).json()
    assert again["letter"] == "B" and again["changed"] == 2
    assert client.delete(f"{API}/{full['id']}").status_code == 422  # it has revisions

    # Export: the document number, revision and title name the file and go in its properties.
    assert client.get(f"{API}/revisions/{again['id']}/name").json()["name"] == "E-SCH-001_B Lighting Cable Schedule.xlsx"
    assert client.get(f"{API}/revisions/{pa['id']}/name", params={"format": "csv"}).json()["name"] == "100 area only_A.csv"
    wb = load_workbook(io.BytesIO(client.post(f"{API}/revisions/{again['id']}/export", json={}).content))
    assert wb.properties.subject == "E-SCH-001 Rev B" and wb["Schedule"].max_row == 20
    out = client.post(f"{API}/revisions/{pa['id']}/export", json={"format": "csv", "path": str(tmp_path / "part")}).json()
    assert out["path"].endswith("part.csv") and (tmp_path / "part.csv").read_text(encoding="utf-8-sig").startswith("TEMPLATE,")

    # Everything survives a restart; the dashboard and the change log know about it.
    storage.configure(data_dir)
    d = client.get(f"{API}/{full['id']}").json()
    assert [(r["letter"], r["description"]) for r in d["revisions"]] == [("B", "IFC"), ("A", "For review")]
    summary = next(s for s in client.get(API).json()["deliverables"] if s["deliverable"]["id"] == full["id"])
    assert (summary["latest"]["letter"], summary["revisions"]) == ("B", 2)
    counts = client.get("/api/dashboard").json()["counts"]
    assert (counts["deliverables"], counts["deliverable_revisions"]) == (2, 3)
    log = client.get("/api/audit", params={"entity": "deliverable_revision"}).json()
    entries = log["entries"] if isinstance(log, dict) else log
    notes = [c["new"] for e in entries for c in e["changes"] if c["path"] == "(note)"]
    assert "Rev B withdrawn: Issued too early" in notes and notes.count("Rev B issued") == 2


def test_issue_from_an_earlier_build() -> None:
    rid = _generator()
    d = _new(rid)
    b1 = _build(rid)
    _rename_run(rid, 0, "LATER")
    _build(rid)
    rev = client.post(f"{API}/{d['id']}/revisions", json={"build_id": b1["id"]}).json()
    assert rev["build_seq"] == 1
    rows = client.get(f"{API}/revisions/{rev['id']}").json()["result"]["rows"]
    assert not any("LATER" in str(c) for r in rows for c in r["cells"])
    assert client.post(f"{API}/{d['id']}/revisions", json={"build_id": "nope"}).status_code == 422


# -- deliverables generated from the Project Load List ------------------------------------------

def _project(kind: str, **more) -> dict:
    res = client.post(API, json={"type": kind, "name": f"Project {kind}", "source": "project"} | more)
    assert res.status_code == 200, res.text
    return res.json()


def _cells(did: str) -> list[list]:
    cur = client.get(f"{API}/{did}", params={"rows": True}).json()["current"]
    return [r["cells"] for r in cur["result"]["rows"]]


def test_deliverables_from_the_project_load_list() -> None:
    assert client.post("/api/sample-data").status_code == 200
    ov = client.get(API).json()
    assert ov["project_columns"]["Cable Schedule"][:2] == ["Cable Number", "From"]
    for s in ov["deliverables"]:  # the sample's own deliverables are not needed here
        assert client.delete(f"{API}/{s['deliverable']['id']}").status_code == 200

    # every type but the Distribution Panel, whose content is a panel's schedule (see test_distribution_panels_api)
    made = {kind: _project(kind) for kind in ov["types"] if kind != "Distribution Panel"}
    for kind, d in made.items():
        detail = client.get(f"{API}/{d['id']}", params={"rows": True}).json()
        cur = detail["current"]
        master = {"Cable Schedule": "Project Master Cable Schedule", "Equipment List": "Project Master Equipment List",
                  "Instrument List": "Project Master Instrument List", "PLC I/O List": "Project Master IO List"}
        assert detail["generator"] == master.get(kind, "Project Master Load List") and cur["source"] == "project"
        assert cur["problem"] is None and cur["rows"] > 0 and cur["warnings"] == []
        assert cur["result"]["header"] == ov["project_columns"][kind]
    cables = _cells(made["Cable Schedule"]["id"])
    first = next(c for c in cables if c[0] == "P-101-P1")
    assert first[1:5] == ["MCC-1", "Motor control centre 1", "P-101", "Feed pump A"]
    assert first[5:9] == ["Power", "AC_415V - Power - 3C+E - 2.5", "3C+E", 2.5]  # looked up in Cable Types
    assert [c[0] for c in cables if c[3] == "C-401"] == ["C-401-P1", "C-401-P2"]  # two in parallel
    assert [c[11] for c in cables if c[3] == "MSB-1"] == ["L1", "L2", "L3", "N"] * 2 + ["E"]  # single cores and their earth
    assert len(_cells(made["Load List"]["id"])) == 12
    # both generators are in a master list: the sample runsheet's three pumps add an instrument each
    instruments = _cells(made["Instrument List"]["id"])
    assert [(c[0], c[-2], c[-1]) for c in instruments if c[-2] == "Instrument"] == [
        ("P-101-PTA", "Instrument", "TRUE"), ("P-102-PTB", "Instrument", "TRUE"), ("P-103-PT", "Instrument", "FALSE")]
    assert {c[-2] for c in instruments} == {"Power", "Instrument"} and first[-2:] == ["Power", "TRUE"]

    # a deliverable keeps the rows and the columns it chooses, in its order
    plc = client.put(f"{API}/{made['PLC I/O List']['id']}", json=dict(made["PLC I/O List"], filter_column="Confirmed", filter_values=["TRUE"],
                                                                      columns=["Channel", "Tag", "Generator"]))
    assert plc.status_code == 200 and plc.json()["columns"] == ["Channel", "Tag", "Generator"], plc.text
    cur = client.get(f"{API}/{plc.json()['id']}", params={"rows": True}).json()["current"]
    assert cur["result"]["header"] == ["Channel", "Tag", "Generator"] and "P-103-PT" not in [r["cells"][1] for r in cur["result"]["rows"]]
    assert "P-101-PTA" in [r["cells"][1] for r in cur["result"]["rows"]]
    rev = client.post(f"{API}/{plc.json()['id']}/revisions", json={}).json()
    assert client.get(f"{API}/revisions/{rev['id']}").json()["result"]["header"] == ["Channel", "Tag", "Generator"]
    no_key = client.put(f"{API}/{plc.json()['id']}", json=dict(plc.json(), columns=["Channel"]))
    assert no_key.status_code == 422 and "Keep the Tag column" in no_key.json()["fields"]["columns"]

    # a filter on one of the list's columns; a column it doesn't have is refused
    part = _project("Cable Schedule", name="MCC-1 cables", filter_column="From", filter_values=["MCC-1"])
    assert {c[1] for c in _cells(part["id"])} == {"MCC-1"}
    bad = client.post(API, json={"type": "Cable Schedule", "name": "x", "source": "project", "filter_column": "Zone"})
    assert bad.status_code == 422 and "filter_column" in bad.json()["fields"]

    cable = made["Cable Schedule"]
    rev_a = client.post(f"{API}/{cable['id']}/revisions", json={"description": "For review"}).json()
    assert rev_a["letter"] == "A" and rev_a["rows"] == len(cables)

    # a load with no load type blocks issuing, and is named
    loads = client.get("/api/loadlist").json()["rows"]
    pump = next(r for r in loads if r["values"].get("tag") == "P-101")
    key = {"recipe_id": pump["recipe_id"], "key": pump["key"]}
    assert client.put("/api/loadlist/allocations", json={"rows": [key], "load_type_id": None}).status_code == 200
    cur = client.get(f"{API}/{cable['id']}").json()["current"]
    assert "1 load(s)" in cur["problem"] and "P-101" in cur["problem"]
    no = client.post(f"{API}/{cable['id']}/revisions", json={})
    assert no.status_code == 422 and "P-101" in no.json()["detail"]
    assert client.put("/api/loadlist/allocations", json={"rows": [key], "load_type_id": "sdol"}).status_code == 200

    # change a template row: the current content differs from Rev A, and Rev B records it
    types = client.get("/api/keylists/load-types").json()["items"]
    dol = next(t for t in types if t["code"] == "DOL")
    dol["rows"]["cable_schedule"][0]["Remarks"] = "Run on ladder"
    dol["rows"]["cable_schedule"].append({"Cable Number": "<<Tag>>-E1", "From": "<<Tag>>", "To": "Earth bar", "Cable Type": "Earth"})
    assert client.put("/api/keylists/load-types", json={"items": types}).status_code == 200
    cur = client.get(f"{API}/{cable['id']}").json()["current"]
    assert cur["problem"] is None and cur["changes"]["added"] == 4 and cur["changes"]["changed"] == 4
    rev_b = client.post(f"{API}/{cable['id']}/revisions", json={"description": "Earths added"}).json()
    assert (rev_b["letter"], rev_b["added"], rev_b["changed"], rev_b["build_seq"]) == ("B", 4, 4, 0)
    a = client.get(f"{API}/revisions/{rev_a['id']}").json()
    assert not any(r["cells"][0] == "P-101-E1" for r in a["result"]["rows"])  # Rev A is frozen

    # the load's cable details drive the schedule: a bigger cable in parallel, then one the table doesn't have
    assert client.put("/api/loadlist/allocations", json={"rows": [key], "cable_size": "70", "cable_insulation": "xlpe",
                                                         "cable_parallel": 2}).status_code == 200
    p101 = [c for c in _cells(cable["id"]) if c[0].startswith("P-101-P")]
    assert [(c[0], c[6], c[8]) for c in p101] == [("P-101-P1", "AC_415V - Power - 3C+E - 70", 70), ("P-101-P2", "AC_415V - Power - 3C+E - 70", 70)]
    cur = client.get(f"{API}/{cable['id']}").json()["current"]
    assert (cur["changes"]["added"], cur["warnings"]) == (1, [])
    assert client.put("/api/loadlist/allocations", json={"rows": [key], "cable_insulation": "PVC"}).status_code == 200
    cur = client.get(f"{API}/{cable['id']}").json()["current"]
    assert cur["problem"] is None and cur["warnings"] == ["No cable for 1 load(s) (no cable type is Power 3C+E 70 mm² PVC): P-101"]
    assert client.post(f"{API}/{cable['id']}/revisions", json={}).json()["letter"] == "C"  # a warning does not block
    wb = load_workbook(io.BytesIO(client.post(f"{API}/revisions/{rev_b['id']}/export", json={}).content))
    assert any(row[0] == "P-101-E1" for row in wb.active.iter_rows(values_only=True))


def test_a_project_deliverable_with_no_loads_or_unknown_tags() -> None:
    d = _project("Equipment List")
    cur = client.get(f"{API}/{d['id']}").json()["current"]
    assert cur["problem"].startswith("Its project master list has no rows yet")
    assert client.post(f"{API}/{d['id']}/revisions", json={}).status_code == 422

    client.post("/api/sample-data")
    types = client.get("/api/keylists/load-types").json()["items"]
    types[0]["rows"]["equipment_list"][0]["Remarks"] = "See <<NoSuchTag>>"
    assert client.put("/api/keylists/load-types", json={"items": types}).status_code == 200
    cur = client.get(f"{API}/{d['id']}").json()["current"]
    assert cur["problem"] is None and "NoSuchTag" in cur["warnings"][0]
    assert client.post(f"{API}/{d['id']}/revisions", json={}).status_code == 200  # a warning, not a block
