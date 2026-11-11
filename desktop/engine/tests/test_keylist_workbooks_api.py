# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

from workbench_desktop import storage
from workbench_desktop.app import app

client = TestClient(app)
API = "/api/list-workbooks"
LISTS = {"plant-areas": "/api/keylists/plant-areas", "equipment-packages": "/api/keylists/equipment-packages",
         "load-types": "/api/keylists/load-types", "equipment-codes": "/api/keylists/equipment-codes",
         "instrument-codes": "/api/keylists/instrument-codes", "cable-types": "/api/keylists/cable-types", "eel": "/api/eel",
         "load-list": "/api/loadlist", "distribution-panels": "/api/distribution-panels"}


@pytest.fixture(autouse=True)
def data_dir(tmp_path: Path):
    storage.configure(tmp_path)
    client.post("/api/sample-data")
    yield tmp_path


def _export(list_id: str) -> bytes:
    res = client.post(f"{API}/{list_id}/export", json={})
    assert res.status_code == 200, res.text
    return res.content


def _import(list_id: str, data: bytes, apply: bool = False):
    return client.post(f"{API}/{list_id}/import", params={"filename": "list.xlsx", "apply": apply}, content=data)


def _edit(data: bytes, change) -> bytes:
    wb = load_workbook(io.BytesIO(data))
    change(wb)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _state(list_id: str):
    """A list as its own API gives it, without the times it was saved at."""
    def strip(v):
        if isinstance(v, dict):
            return {k: strip(x) for k, x in v.items() if k != "updated_at"}
        return [strip(x) for x in v] if isinstance(v, list) else v
    return strip(client.get(LISTS[list_id]).json())


@pytest.mark.parametrize("list_id", list(LISTS))
def test_every_list_exports_and_imports_back_unchanged(list_id: str) -> None:
    before = _state(list_id)
    data = _export(list_id)
    preview = _import(list_id, data)
    assert preview.status_code == 200, preview.text
    assert preview.json()["applied"] is False and "removed." in preview.json()["summary"] + "removed."
    assert _state(list_id) == before  # a preview saves nothing
    if list_id != "load-list":
        assert " 0 new" in preview.json()["summary"] and "Nothing would be removed" in preview.json()["summary"]
    else:
        assert preview.json()["summary"].startswith("0 row(s)")
    done = _import(list_id, data, apply=True)
    assert done.status_code == 200 and done.json()["applied"] is True, done.text
    after = _state(list_id)
    if list_id == "distribution-panels":  # circuits and headings get new ids; everything else is the same
        for view in (before, after):
            for p in view["doc"]["panels"]:
                for x in p["entries"] + p["dividers"]:
                    x["id"] = ""
            for s in view["schedules"].values():
                for r in s["rows"]:
                    r["entry_id"] = r["entry_id"] and ""
    assert after == before


def test_export_to_a_path_and_unknown_lists(tmp_path: Path) -> None:
    out = tmp_path / "areas"
    assert client.post(f"{API}/plant-areas/export", json={"path": str(out)}).json() == {"path": str(out) + ".xlsx"}
    wb = load_workbook(str(out) + ".xlsx")
    assert wb.sheetnames == ["Plant Areas"] and [c.value for c in wb["Plant Areas"][1]] == [
        "Tag number", "Description", "Type", "WBS number", "Parent tag"]
    assert client.post(f"{API}/nope/export", json={}).status_code == 404
    assert _import("plant-areas", b"not a workbook").status_code == 400
    assert "no \"Plant Areas\" sheet" in _import("plant-areas", _export("cable-types")).json()["detail"]


def test_import_keeps_ids_adds_and_removes() -> None:
    old = {n["tag"]: n["id"] for n in client.get(LISTS["plant-areas"]).json()["nodes"]}

    def change(wb) -> None:
        ws = wb["Plant Areas"]
        for row in ws.iter_rows(min_row=2):
            if str(row[0].value) == "600":  # Utilities: nothing refers to it
                ws.delete_rows(row[0].row)
                break
        ws.append(["700", "New area", "Area", "1.7", "W-1"])
        for row in ws.iter_rows(min_row=2):
            if str(row[0].value) == "100":
                row[1].value = "Feed area (renamed)"
    data = _edit(_export("plant-areas"), change)
    assert "1 new" in _import("plant-areas", data).json()["summary"] and "1 plant area(s) of the list are not in the file" in _import(
        "plant-areas", data).json()["summary"]
    assert _import("plant-areas", data, apply=True).json()["applied"] is True
    new = {n["tag"]: n for n in client.get(LISTS["plant-areas"]).json()["nodes"]}
    assert "600" not in new and new["100"]["description"] == "Feed area (renamed)" and new["700"]["parent_id"] == old["W-1"]
    assert {t: n["id"] for t, n in new.items() if t in old} == {t: i for t, i in old.items() if t != "600"}  # ids kept
    assert client.get("/api/audit", params={"entity": "plant_areas"}).json()["entries"]


def test_a_file_that_breaks_the_rules_changes_nothing() -> None:
    before = _state("plant-areas")

    def clash(wb) -> None:
        wb["Plant Areas"].append(["100", "Twice", "Area", None, None])
    bad = _import("plant-areas", _edit(_export("plant-areas"), clash), apply=True)
    assert bad.status_code in (400, 422) and _state("plant-areas") == before

    def drop_used(wb) -> None:  # the sample MEL's loads are allocated to area 100
        ws = wb["Plant Areas"]
        for row in list(ws.iter_rows(min_row=2)):
            if str(row[0].value) in ("100", "B-110", "R-111", "PNL-111"):
                ws.delete_rows(row[0].row)
    client.put("/api/loadlist/allocations", json={"rows": [{"recipe_id": r["recipe_id"], "key": r["key"]} for r in client.get(
        "/api/loadlist").json()["rows"] if r["values"].get("tag") == "P-101"], "plant_area_id": next(
            n["id"] for n in before["nodes"] if n["tag"] == "100")})
    refused = _import("plant-areas", _edit(_export("plant-areas"), drop_used), apply=True)
    assert refused.status_code == 422 and "can't be deleted" in refused.json()["detail"]

    def bad_type(wb) -> None:
        wb["Load Types"]["C2"].value = "Horsepower"
    res = _import("load-types", _edit(_export("load-types"), bad_type))
    assert res.status_code == 422 and "DOL: Choose kW or Amps" in res.json()["detail"]


def test_load_types_rows_and_the_load_list_allocations() -> None:
    wb = load_workbook(io.BytesIO(_export("load-types")))
    assert wb.sheetnames == ["Load Types", "Cable Schedule rows", "Instrument List rows", "PLC I-O List rows", "Equipment List rows"] or \
        set(wb.sheetnames) == {"Load Types", "Cable Schedule rows", "Equipment List rows", "Instrument List rows", "PLC I-O List rows"}
    assert wb["Cable Schedule rows"]["A2"].value == "DOL" and wb["Cable Schedule rows"].max_row > 4

    def change(wb) -> None:
        ws = wb["Load List"]
        head = [c.value for c in ws[1]]
        for row in ws.iter_rows(min_row=2):
            if row[head.index("Tag")].value == "P-101":
                row[head.index("Supplied from")].value = "MCC-2"
                row[head.index("Cable length (m)")].value = 42
                row[head.index("Plant area")].value = "No such area"
        ws.append(["Somewhere", "X-1", "X-1"])
    data = _edit(_export("load-list"), change)
    preview = _import("load-list", data).json()
    assert preview["summary"].startswith("1 row(s)") and any("No such area" in n for n in preview["notes"])
    assert any("1 row(s) of the file are not in the Load List" in n for n in preview["notes"])
    done = _import("load-list", data, apply=True).json()
    assert done["applied"] and "1 row(s) changed." in done["notes"]
    row = next(r for r in client.get("/api/loadlist").json()["rows"] if r["values"].get("tag") == "P-101")
    assert (row["supplied_from"], row["supplied_from_by"], row["cable_length"], row["plant_area_id"]) == ("eel/smcc2", "user", 42, None)


def test_a_distribution_panel_typed_in_excel() -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Panels"
    ws.append(["Panel", "Load List panel", "Type", "Ways", "Isolator & chassis rating (A)"])
    ws.append(["2236-DP3310", None, "Three-phase", 4, 250])
    ws.append(["MCC-2", "MCC-2", "Three-phase", 12, 630])
    c = wb.create_sheet("Circuits")
    c.append(["Panel", "Way", "Phase", "Poles", "What", "Load tag", "Description", "Load type", "Qty", "Watts (Ea.)", "CB rating (A)"])
    c.append(["2236-DP3310", 1, "Red", 1, "Other", None, "Lighting level 1", "Light - Walkway", 12, 5, 16])
    c.append(["2236-DP3310", 1, "White", 1, "Spare CB", None, None, None, None, None, 16])
    for phase, watts in (("Red", 20), ("White", 20), ("Blue", 20)):
        c.append(["2236-DP3310", 4, phase, 3, "Other", None, "Belt splicing outlet", "Socket Outlet 3ph - 32A", 1, watts, 32])
    c.append(["MCC-2", 1, "Red", 3, "Load", "C-401"])
    c.append(["MCC-2", 2, "Red", 3, "Load", "NOT-A-LOAD"])
    h = wb.create_sheet("Headings")
    h.append(["Panel", "Above way", "Text"])
    h.append(["2236-DP3310", 3, "Lighting Contactor"])
    out = io.BytesIO()
    wb.save(out)
    res = _import("distribution-panels", out.getvalue(), apply=True)
    assert res.status_code == 200, res.text
    assert "1 new" in res.json()["summary"] and any("NOT-A-LOAD" in n for n in res.json()["notes"])
    view = client.get("/api/distribution-panels").json()
    panels = {p["tag"]: p for p in view["doc"]["panels"]}
    assert panels["MCC-2"]["id"] == "sdp1" and panels["MCC-2"]["load_ref"] == "eel/smcc2"  # the sample panel, kept by its tag
    dp = view["schedules"][panels["2236-DP3310"]["id"]]
    by = {r["circuit"]: r for r in dp["rows"]}
    assert (by["QR1"]["total_w"], by["QR1"]["cb_rating"], by["QW1"]["load_type"], by["QR4"]["span"], by["QB4"]["cb_rating"]) == (
        60, 16, "DP - Spare CB", 3, 32)
    assert by["QR3"]["section"] == "Lighting Contactor" and dp["totals"]["total_kw"] == 0.12
    mcc = view["schedules"]["sdp1"]
    assert [r["tag"] for r in mcc["rows"] if r["span"]] [:1] == ["C-401"] and len(mcc["unplaced"]) == 4


def test_reset_the_load_list_reads_the_imports_again() -> None:
    rows = client.get("/api/loadlist").json()["rows"]
    p101 = next(r for r in rows if r["values"].get("tag") == "P-101")
    ref = {"rows": [{"recipe_id": p101["recipe_id"], "key": p101["key"]}]}
    assert client.put("/api/loadlist/allocations", json=ref | {"supplied_from": "eel/smcc2", "cable_size": "4"}).status_code == 200
    res = client.post(f"{API}/load-list/reset")
    assert res.status_code == 200 and res.json()["message"] == "12 remembered row(s) forgotten. The imports were read again: 12 row(s)."
    after = next(r for r in client.get("/api/loadlist").json()["rows"] if r["values"].get("tag") == "P-101")
    # back to what the import gives: fed from MCC-1 (filled in automatically), no cable details
    assert (after["supplied_from"], after["supplied_from_by"], after["cable_size"], after["load_type_by"]) == ("eel/smcc1", "auto", "", "auto")
    log = client.get("/api/audit", params={"entity": "load_list"}).json()["entries"]
    assert "Reset: every row forgotten" in str(log)


def test_reset_the_other_lists_obeys_their_rules() -> None:
    refused = client.post(f"{API}/equipment-codes/reset")  # the Electrical Equipment List uses them
    assert refused.status_code == 422 and "was not reset" in refused.json()["detail"]
    assert client.get(LISTS["equipment-codes"]).json()["items"]
    assert client.post(f"{API}/distribution-panels/reset").status_code == 422  # a deliverable issues the panel
    assert client.post(f"{API}/instrument-codes/reset").json() == {"message": "Instrument Codes is empty."}
    assert client.get(LISTS["instrument-codes"]).json()["items"] == []
    assert "218 default" in client.post(f"{API}/cable-types/reset").json()["message"]
    assert client.post(f"{API}/plc/reset").status_code == 200 and client.get("/api/plc").json()["plc"]["systems"] == []
    assert client.post(f"{API}/nope/reset").status_code == 404
