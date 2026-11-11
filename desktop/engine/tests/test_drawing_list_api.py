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

client = TestClient(app)
URL, ENUMS = "/api/drawing-list", "/api/enums"
ANN = {"X-Workbench-User": "ACME\\ann", "X-Workbench-Machine": "PC-01"}
BOB = {"X-Workbench-User": "ACME\\bob", "X-Workbench-Machine": "PC-02"}


@pytest.fixture(autouse=True)
def data_dir(tmp_path: Path):
    storage.configure(tmp_path)
    yield tmp_path


def test_a_project_starts_with_the_default_enums_and_no_drawings() -> None:
    view = client.get(ENUMS).json()
    assert view["titles"] == {"disciplines": "Disciplines", "drawing_types": "Drawing types", "drawing_statuses": "Drawing statuses"}
    assert [d["code"] for d in view["enums"]["disciplines"]] == ["E", "I", "M", "P", "C", "S", "H", "PR", "G"]
    assert len(view["enums"]["drawing_types"]) == 16 and view["enums"]["drawing_statuses"][4] == {"id": "ds5", "code": "IFC", "name": "Issued for Construction"}
    assert view["need_code"] == ["disciplines"] and view["in_use"] == {}
    drawings = client.get(URL).json()
    assert drawings["items"] == [] and [c["heading"] for c in drawings["columns"]][:2] == ["Drawing number", "Project name"]
    assert [i["name"] for i in drawings["choices"]["drawing_type"]][:2] == ["Single Line Diagram", "Schematic"]
    ov = client.get("/api/keylists").json()
    assert ov["drawing_list"] == {"items": 0} and ov["enums"] == {"items": 33} and ov["disciplines"][-1] == {"code": "G", "name": "General"}


def test_drawings_fixed_choices_and_equipment_warnings() -> None:
    client.post("/api/sample-data")
    view = client.get(URL).json()
    sld = view["items"][0]
    assert (sld["number"], sld["discipline"], sld["drawing_type"], sld["status"], sld["issue_date"], sld["unknown_equipment"]) == (
        "100-E-SLD-001", "E", "Single Line Diagram", "IFC", "14/03/2026", [])
    assert len(view["items"]) == 4 and view["items"][2]["discipline"] == "PR"

    rows = view["items"] + [{"id": "n1", "number": "100-I-LOOP-001", "discipline": "instrumentation", "drawing_type": "Loop Diagram",
                             "status": "IFR", "issue_date": "2026-05-01", "equipment_reference": "P-101; NOT-A-TAG"}]
    ann = client.get(URL, headers=ANN).headers["ETag"]
    bob = client.get(URL, headers=BOB).headers["ETag"]
    ok = client.put(URL, json={"items": rows}, headers={**ANN, "If-Match": ann})
    assert ok.status_code == 200, ok.text
    new = ok.json()["items"][4]
    assert (new["discipline"], new["discipline_id"], new["issue_date"], new["equipment_reference"], new["unknown_equipment"]) == (
        "I", "d-i", "01/05/2026", "P-101, NOT-A-TAG", ["NOT-A-TAG"])  # a tag that isn't found is a warning, not an error
    assert ok.json()["items"][0] == sld  # an unchanged drawing round-trips as it is shown
    assert client.put(URL, json={"items": []}, headers={**BOB, "If-Match": bob}).status_code == 409

    bad = client.put(URL, json={"items": rows + [{"id": "x1", "number": "100-E-SLD-001", "status": "Finished", "issue_date": "soon"},
                                                 {"id": "x2", "number": " "}]})
    assert bad.status_code == 422 and set(bad.json()["fields"]) == {"x1.number", "x1.status", "x1.issue_date", "x2.number"}
    assert "100-E-SLD-001: " in bad.json()["detail"] and len(client.get(URL).json()["items"]) == 5
    assert "Drawing List" in str(client.get("/api/audit", params={"entity": "drawing_list"}).json())


def test_enums_are_edited_per_project_and_items_in_use_are_kept() -> None:
    client.post("/api/sample-data")
    view = client.get(ENUMS).json()
    enums = view["enums"]
    assert view["in_use"]["d-e"] == 6 and view["in_use"]["ds5"] == 1  # 3 drawings and 3 equipment codes use Electrical

    # add a status, rename one that is in use: the drawing follows
    enums["drawing_statuses"].append({"id": "mine", "code": "IFI", "name": "Issued for Information"})
    next(s for s in enums["drawing_statuses"] if s["id"] == "ds5")["code"] = "AFC"
    saved = client.put(ENUMS, json=enums)
    assert saved.status_code == 200, saved.text
    assert client.get(URL).json()["items"][0]["status"] == "AFC" and client.get(URL).json()["choices"]["status"][-1]["code"] == "IFI"

    # an item in use can't be removed; a discipline equipment codes use keeps its code
    gone = dict(enums, drawing_types=[t for t in enums["drawing_types"] if t["name"] != "P&ID"])
    refused = client.put(ENUMS, json=gone)
    assert refused.status_code == 422 and "P&ID (1 use)" in refused.json()["detail"]
    recoded = dict(enums, disciplines=[dict(d, code="EL") if d["id"] == "d-e" else d for d in enums["disciplines"]])
    refused = client.put(ENUMS, json=recoded)
    assert refused.status_code == 422 and refused.json()["fields"] == {"d-e.code": "Equipment codes use the discipline E: its code can't change"}
    unused = dict(enums, drawing_types=[t for t in enums["drawing_types"] if t["name"] != "Datasheet"])
    assert client.put(ENUMS, json=unused).status_code == 200
    dup = dict(enums, disciplines=enums["disciplines"] + [{"id": "z", "code": "e", "name": "Again"}])
    assert client.put(ENUMS, json=dup).json()["fields"] == {"z.code": "Code 'e' is used twice"}

    # Equipment Codes pick from the project's disciplines
    enums = client.get(ENUMS).json()["enums"]
    enums["disciplines"].append({"id": "fire", "code": "F", "name": "Fire"})
    assert client.put(ENUMS, json=enums).status_code == 200
    codes = client.get("/api/keylists/equipment-codes").json()["items"]
    ok = client.put("/api/keylists/equipment-codes", json={"items": codes + [{"id": "fp", "code": "FP", "name": "Fire pump", "disciplines": ["F", "PR"]}]})
    assert ok.status_code == 200 and ok.json()["items"][-1]["disciplines"] == ["PR", "F"]
    bad = client.put("/api/keylists/equipment-codes", json={"items": codes + [{"id": "q", "code": "Q", "name": "Q", "disciplines": ["ZZ"]}]})
    assert bad.status_code == 422 and client.get("/api/keylists").json()["disciplines"][-1] == {"code": "F", "name": "Fire"}
    assert "Enums" in str(client.get("/api/audit", params={"entity": "enums"}).json())


def test_the_drawing_list_workbook() -> None:
    client.post("/api/sample-data")
    data = client.post("/api/list-workbooks/drawing-list/export", json={}).content
    wb = load_workbook(io.BytesIO(data))
    ws = wb["Drawing List"]
    assert [c.value for c in ws[1]] == ["Drawing number", "Project name", "Title 1", "Title 2", "Title 3", "Drawing discipline",
                                        "Drawing type", "Revision", "Status", "Issue date", "Vendor drg number", "Vendor reference",
                                        "Equipment reference", "Scope", "Hyperlink"]
    assert (ws["A2"].value, ws["F2"].value, ws["I2"].value, ws["J2"].value) == ("100-E-SLD-001", "E", "IFC", "14/03/2026")
    old = {d["number"]: d["id"] for d in client.get(URL).json()["items"]}

    ws.append(["100-E-TER-001", "Sample plant", "MCC-1", "Terminations", None, "Electrical", "Termination Diagram", "A", "ifr", "2026-06-01",
               None, None, None, None, "https://dms.example.com/100-E-TER-001"])
    assert ws["O2"].value == "https://dms.example.com/drawings/100-E-SLD-001"
    ws["I2"].value = "As Built"  # a status by its name
    out = io.BytesIO()
    wb.save(out)
    res = client.post("/api/list-workbooks/drawing-list/import", params={"filename": "d.xlsx", "apply": True}, content=out.getvalue())
    assert res.status_code == 200 and "1 new" in res.json()["summary"], res.text
    items = client.get(URL).json()["items"]
    assert {d["number"]: d["id"] for d in items if d["number"] in old} == old  # drawings keep their identity
    assert (items[0]["status"], items[-1]["discipline"], items[-1]["status"], items[-1]["issue_date"]) == ("AB", "E", "IFR", "01/06/2026")
    assert items[-1]["hyperlink"] == "https://dms.example.com/100-E-TER-001"
    bad = client.put(URL, json={"items": [dict(items[0], hyperlink="javascript:alert(1)")]})
    assert bad.status_code == 422 and set(bad.json()["fields"]) == {f"{items[0]['id']}.hyperlink"}

    ws["I3"].value = "Nearly done"
    out = io.BytesIO()
    wb.save(out)
    bad = client.post("/api/list-workbooks/drawing-list/import", params={"filename": "d.xlsx", "apply": True}, content=out.getvalue())
    assert bad.status_code == 422 and "100-E-SCH-101: 'Nearly done' is not a status" in bad.json()["detail"]
    assert client.get(URL).json()["items"] == items
