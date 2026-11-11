# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Generators API on the invented sample workbook (samples/generator-sample.xlsx)."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from workbench_desktop import storage
from workbench_desktop.app import app

SAMPLES = Path(__file__).resolve().parents[3] / "samples"
SAMPLE = SAMPLES / "generator-sample.xlsx"
client = TestClient(app)


@pytest.fixture(autouse=True)
def data_dir(tmp_path: Path):
    storage.configure(tmp_path)
    yield tmp_path


def _import() -> dict:
    res = client.post("/api/generators/import", params={"filename": SAMPLE.name}, content=SAMPLE.read_bytes())
    assert res.status_code == 200, res.text
    return res.json()


def _build(rid: str, **body) -> dict:
    res = client.post(f"/api/generators/{rid}/builds", json=body)
    assert res.status_code == 200, res.text
    return res.json()


def _col(build: dict, name: str) -> list:
    r = build["result"]
    i = r["header"].index(name)
    return [row["cells"][i] for row in r["rows"] if row["run_row_id"]]


def test_import_get_list_and_tables():
    out = _import()
    rec, rep = out["record"], out["report"]
    assert rec["name"] == "Demo Lighting Cable Schedule" and rec["kind"] == "dp" and rec["source_file"] == SAMPLE.name
    assert rep["templates"] == 4 and rep["template_rows"] == 6 and not rep["unmapped_formulas"]
    assert rec["generator"]["tables"] == {}  # tables are stored separately
    assert {t["name"] for t in rec["tables"]} == {"Codes", "CableTypes"}
    lst = client.get("/api/generators").json()
    assert [g["id"] for g in lst] == [rec["id"]] and lst[0]["runs"] == 10 and lst[0]["last_build"] is None
    t = client.get(f"/api/generators/{rec['id']}/tables/Codes").json()
    assert len(t["rows"]) == 5
    assert client.get(f"/api/generators/{rec['id']}/tables/Nope").status_code == 404
    assert client.get("/api/generators/nope").status_code == 404


def test_import_rejects_bad_files():
    res = client.post("/api/generators/import", params={"filename": "x.xlsx"}, content=b"not a workbook")
    assert res.status_code == 400 and "Not an Excel workbook" in res.json()["detail"]
    assert client.post("/api/generators/import", params={"filename": "x.xlsx"}, content=b"").status_code == 400


def test_build_rebuild_add_run_and_change_report():
    rid = _import()["record"]["id"]
    b1 = _build(rid)
    assert b1["seq"] == 1 and b1["stats"]["processed"] == 8 and b1["stats"]["rows_written"] == 12
    assert b1["added"] is None and b1["stats"]["no_template"] == 1
    b2 = _build(rid)
    assert (b2["seq"], b2["added"], b2["removed"], b2["changed"]) == (2, 0, 0, 0)
    assert b2["input_hash"] == b1["input_hash"]

    # Acceptance 3: add a run, pick a template, build, see it in the change report
    rec = client.get(f"/api/generators/{rid}").json()
    gen = rec["generator"]
    new = list(gen["runsheet"]["rows"][2]["values"])  # a socket outlet run
    new[2], new[5], new[6], new[11] = 11, "WORKSHOP SPARE OUTLETS", "200-SO03", 3
    gen["runsheet"]["rows"].append({"id": "new-1", "values": new})
    res = client.put(f"/api/generators/{rid}", json={"name": rec["name"], "generator": gen})
    assert res.status_code == 200, res.text
    b3 = _build(rid)
    assert (b3["added"], b3["removed"], b3["changed"]) == (1, 0, 0) and b3["input_hash"] != b1["input_hash"]
    full = client.get(f"/api/generators/builds/{b3['id']}").json()
    added = [e for e in full["result"]["changes"]["entries"] if e["kind"] == "added"]
    assert [e["key"] for e in added] == ["200LB02-P3-P1"]
    assert "200LB02-P3-P1" in _col(full, "Cable Number")
    assert [b["seq"] for b in client.get(f"/api/generators/{rid}/builds").json()] == [3, 2, 1]
    assert client.get("/api/generators").json()[0]["last_build"]["seq"] == 3


def test_build_run_range_and_all_runs():
    rid = _import()["record"]["id"]
    b = _build(rid, run_from=3, run_up_to=5)
    assert b["stats"]["processed"] == 2 and (b["run_from"], b["run_up_to"]) == (3, 5)
    b = _build(rid, use_config_range=False)
    assert b["stats"]["processed"] == 8 and b["run_from"] is None


def test_locked_run_keeps_previous_rows():
    rid = _import()["record"]["id"]
    _build(rid)
    rec = client.get(f"/api/generators/{rid}").json()
    gen = rec["generator"]
    row = gen["runsheet"]["rows"][6]["values"]  # run 7, panel feed
    row[5], row[14] = "RENAMED LOAD", True
    gen["runsheet"]["rows"][7]["values"][5] = "ALSO RENAMED"  # run 8, not locked
    client.put(f"/api/generators/{rid}", json={"name": rec["name"], "generator": gen})
    b = client.get(f"/api/generators/builds/{_build(rid)['id']}").json()
    assert b["info"]["stats"]["locked_used"] == 1 and b["info"]["changed"] == 1
    to_loc = _col(b, "To Location")
    assert "ADMIN AIR CONDITIONING" in to_loc and "ALSO RENAMED" in to_loc and "RENAMED LOAD" not in to_loc


def test_save_validation():
    rec = _import()["record"]
    gen = rec["generator"]
    gen["runsheet"]["columns"][1]["tag"] = "<<KEY>>"  # duplicate of <<Key>>
    res = client.put(f"/api/generators/{rec['id']}", json={"name": rec["name"], "generator": gen})
    assert res.status_code == 422 and "duplicate tag" in res.json()["fields"]["runsheet"]
    res = client.put(f"/api/generators/{rec['id']}", json={"name": " ", "generator": rec["generator"]})
    assert res.status_code == 422 and "name" in res.json()["fields"]


def test_check_and_preview_with_draft():
    rec = _import()["record"]
    rid = rec["id"]
    chk = client.post(f"/api/generators/{rid}/check", json={}).json()
    assert [f["code"] for f in chk["findings"] if f["severity"] == "ERROR"] == ["C6"]
    assert {e["id"]: e["runs"] for e in chk["template_index"]} == {"10": 2, "20": 3, "30": 2, "40": 1}
    pv = client.post(f"/api/generators/{rid}/preview", json={"run_row_id": "3"}).json()  # run 1
    assert [r["cells"][4] for r in pv["rows"]] == ["100LB01-L1-P1", "100LB01-L1-P2 to P5"]
    assert pv["rows"][1]["sources"][4].startswith('F="<<FromTag_S>>')
    assert pv["rows"][0]["sources"][14] == "computed: concat"
    # an unsaved edit is previewed without saving it
    draft = rec["generator"]
    draft["templates"][0]["rows"][0]["cells"][3]["text"] = "<<FromTag_S>>-SO<<CCT2>>"
    pv = client.post(f"/api/generators/{rid}/preview", json={"run_row_id": "5", "draft": draft}).json()
    assert pv["rows"][0]["cells"][4] == "200LB02-SO1"
    pv = client.post(f"/api/generators/{rid}/preview", json={"run_row_id": "5", "template_id": "30"}).json()
    assert pv["rows"][0]["cells"][12] == "4C+E"  # Cores from template 30
    pv = client.post(f"/api/generators/{rid}/preview", json={"run_row_id": "11"}).json()  # key 99
    assert pv["rows"] == [] and "99" in pv["message"]
    draft["runsheet"]["columns"][1]["tag"] = "<<KEY>>"
    chk = client.post(f"/api/generators/{rid}/check", json={"draft": draft}).json()
    assert chk["findings"][0]["code"] == "C2"


def test_export_blob_and_path(tmp_path: Path):
    rid = _import()["record"]["id"]
    b = _build(rid)
    res = client.post(f"/api/generators/builds/{b['id']}/export", json={"format": "xlsx"})
    assert res.status_code == 200 and 'filename="Demo Lighting Cable Schedule Output' in res.headers["content-disposition"]
    ws = load_workbook(io.BytesIO(res.content))["Schedule"]
    assert ws["E2"].value == "100LB01-L1-P1" and ws.max_row == 1 + 19
    res = client.post(f"/api/generators/builds/{b['id']}/export", json={"format": "csv", "path": str(tmp_path / "out")})
    assert res.json()["path"].endswith("out.csv") and (tmp_path / "out.csv").read_text(encoding="utf-8-sig").startswith("TEMPLATE,")
    res = client.post(f"/api/generators/builds/{b['id']}/export", content=b'{"format":"xlsx"}',
                      headers={"content-type": "text/plain"})
    assert res.status_code in (415, 422)  # refused: a non-JSON post can't trigger a file write
    assert client.get(f"/api/generators/builds/{b['id']}/name").json()["name"].endswith(".xlsx")


def test_persistence_delete_and_dashboard(data_dir: Path):
    rid = _import()["record"]["id"]
    b = _build(rid)
    storage.configure(data_dir)  # reopen the database
    assert client.get(f"/api/generators/{rid}").json()["generator"]["runsheet"]["rows"]
    assert len(client.get(f"/api/generators/{rid}/builds").json()) == 1
    d = client.get("/api/dashboard").json()
    assert d["counts"]["generators"] == 1 and d["counts"]["gen_builds"] == 1
    assert {e["kind"] for e in d["recent"] if e["section"] == "generators"} == {"generator", "build"}
    assert client.delete(f"/api/generators/builds/{b['id']}").json() == {"ok": True}
    assert client.get(f"/api/generators/builds/{b['id']}").status_code == 404
    assert client.delete(f"/api/generators/{rid}").json() == {"ok": True}
    assert client.get("/api/generators").json() == []


# -- PLC hardware: read-only, from the project's PLC List ---------------------------------------

def test_hardware_view_reads_the_plc_list():
    rid = _import()["record"]["id"]
    v = client.get(f"/api/generators/{rid}/hardware").json()
    assert v["hardware"] == {"panels": []} and v["summary"]["cards"] == 0
    card = lambda t: {"card_type_id": t}  # noqa: E731
    plc = {"systems": [{"tag": "PLC1", "racks": [{"tag": "PLC1-RK1", "rack_type_id": "rack",
                                                  "cards": [card("net"), card("di16"), None, card("ai8")]}]}]}
    assert client.put("/api/plc", json=plc).status_code == 200
    v = client.get(f"/api/generators/{rid}/hardware").json()
    assert [r["card"] for r in v["schedule"]] == ["PLC1-RK1-S1", "PLC1-RK1-S2", "PLC1-RK1-S4"]
    assert {k["kind"]: k["channels"] for k in v["summary"]["by_kind"]} == {"Network": 0, "DI": 16, "AI": 8}
    # capacity against the latest IO list build (the sample has no CARD TYPE column)
    _build(rid)
    assert client.get(f"/api/generators/{rid}/hardware").json()["summary"]["demand_column"] is None
    # editing here has moved to the PLC List
    assert client.put(f"/api/generators/{rid}/hardware", json={"panels": []}).status_code == 405
    assert client.get("/api/generators/hardware/catalogue").status_code == 404
    assert client.get("/api/dashboard").json()["counts"]["plc_cards"] == 3
    assert client.get("/api/generators/nope/hardware").status_code == 404


# -- bulk editing workbook -------------------------------------------------------------------------

def test_inputs_export_preview_and_apply(tmp_path: Path):
    rid = _import()["record"]["id"]
    res = client.post(f"/api/generators/{rid}/inputs/export", json={})
    assert res.status_code == 200 and 'inputs.xlsx' in res.headers["content-disposition"]
    wb = load_workbook(io.BytesIO(res.content))
    assert "PLC cards" not in wb.sheetnames and "T Codes" in wb.sheetnames
    wb["RunSheet"]["G3"] = "BULK EDITED"
    wb["T Codes"].append(["R230 - Power - 2C+E - 25"])
    buf = io.BytesIO()
    wb.save(buf)
    q = {"filename": "inputs.xlsx"}
    pv = client.post(f"/api/generators/{rid}/inputs/import", params=q, content=buf.getvalue()).json()
    changed = {s["table"]: (s["added"], s["removed"], s["changed"]) for s in pv["preview"]["sheets"]}
    assert changed["runsheet"] == (0, 0, 1) and changed["table:Codes"] == (1, 0, 0) and "hardware" not in changed
    assert pv["applied"] == [] and pv["record"] is None
    assert client.get(f"/api/generators/{rid}").json()["generator"]["runsheet"]["rows"][0]["values"][5] != "BULK EDITED"
    out = client.post(f"/api/generators/{rid}/inputs/import", params={**q, "apply": "runsheet,table:Codes"},
                      content=buf.getvalue()).json()
    assert out["applied"] == ["runsheet", "table:Codes"]
    assert out["record"]["generator"]["runsheet"]["rows"][0]["values"][5] == "BULK EDITED"
    assert len(client.get(f"/api/generators/{rid}/tables/Codes").json()["rows"]) == 6
    # nothing left to change after applying
    pv = client.post(f"/api/generators/{rid}/inputs/import", params=q, content=buf.getvalue()).json()
    assert {s["table"]: s["changed"] + s["added"] + s["removed"] for s in pv["preview"]["sheets"]}["runsheet"] == 0
    # errors: a sheet with errors can't be applied
    wb["RunSheet"]["A1"] = "x"
    buf = io.BytesIO()
    wb.save(buf)
    res = client.post(f"/api/generators/{rid}/inputs/import", params={**q, "apply": "runsheet"}, content=buf.getvalue())
    assert res.status_code == 422
    assert client.post(f"/api/generators/{rid}/inputs/import", params=q, content=b"nope").status_code == 400
    out = client.post(f"/api/generators/{rid}/inputs/export", json={"path": str(tmp_path / "in")}).json()
    assert out["path"].endswith("in.xlsx") and (tmp_path / "in.xlsx").stat().st_size > 2000


def test_the_two_generators_fill_the_master_lists() -> None:
    types = client.get("/api/generators/types").json()
    assert [(t["id"], t["name"], t["available"]) for t in types] == [("power", "Power", True), ("instrument", "Instrument", True)]
    assert (types[0]["runs"], types[1]["runs"], types[0]["lists"][0]["rows"]) == (0, 0, 0)
    client.post("/api/sample-data")
    power, instrument = client.get("/api/generators/types").json()
    assert (power["runs"], power["templates"], power["missing"]) == (12, 4, [])
    assert (instrument["runs"], instrument["templates"], instrument["unconfirmed"]) == (3, 1, 1)
    assert [x["type"] for x in power["lists"]] == ["Cable Schedule", "Equipment List", "Instrument List", "PLC I/O List"]
    il = next(x for x in instrument["lists"] if x["key"] == "instrument_list")
    pl = next(x for x in power["lists"] if x["key"] == "instrument_list")
    assert (il["master"], il["rows"], il["deliverables"]) == ("Project Master Instrument List", 3, 1)
    assert il["master_rows"] == pl["master_rows"] == il["rows"] + pl["rows"] and pl["rows"] > 0

    masters = client.get("/api/master").json()
    assert [m["name"] for m in masters] == ["Project Master Cable Schedule", "Project Master Equipment List",
                                            "Project Master Instrument List", "Project Master IO List"]
    m = next(x for x in masters if x["key"] == "plc_io_list")
    assert (m["instrument_rows"], m["rows"], m["columns"][-2:]) == (3, m["power_rows"] + 3, ["Generator", "Confirmed"])
    one = client.get("/api/master/plc_io_list").json()
    assert one["result"]["header"] == m["columns"] and len(one["result"]["rows"]) == m["rows"] and one["warnings"] == []
    assert one["result"]["rows"][-1]["cells"][-2:] == ["Instrument", "FALSE"]
    assert client.get("/api/master/nope").status_code == 404
    data = client.post("/api/master/plc_io_list/export", json={"format": "csv"})
    assert data.status_code == 200 and data.text.splitlines()[0].lstrip("\ufeff").startswith("Tag,Description")
