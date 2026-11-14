# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
from __future__ import annotations

import json

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from workbench_desktop import storage
from workbench_desktop.app import app

client = TestClient(app)
URL = "/api/keylists/cable-types"
ANN = {"X-Workbench-User": "ACME\\ann", "X-Workbench-Machine": "PC-01"}
BOB = {"X-Workbench-User": "ACME\\bob", "X-Workbench-Machine": "PC-02"}


@pytest.fixture(autouse=True)
def data_dir(tmp_path: Path):
    storage.configure(tmp_path)
    yield tmp_path


def test_a_project_starts_with_the_default_cable_types() -> None:
    items = client.get(URL).json()["items"]
    assert len(items) == 656 and client.get("/api/keylists").json()["cable_types"] == {"items": 656}  # 218 + the handbook's 438
    assert len({i["code"] for i in items}) == 656
    assert [i["sort"] for i in items] == sorted(i["sort"] for i in items) and (items[0]["sort"], items[-1]["sort"]) == (1, 1437)
    by = {i["sort"]: i for i in items}
    # the handbook's figures (page 67, 2 core V-90 PVC, copper, in air) ride along with the text
    assert by[1] == {"id": "d1", "code": "AC_240V - Power - 2C+E - 1.5", "application": "AC_240V", "type": "Power",
                     "cores": "2C+E", "diameter": "1.5", "voltage": "0.6/1kV", "insulation": "PVC",
                     "description": "Cu-PVC-PVC-V90 (Power)", "sort": 1, "conductor_mm2": 1.5,
                     "ampacity": {"unenclosed_space": 19.0, "touching": 18.0, "enclosed_conduit_in_air": 16.0},
                     "ampacity_source": "Nexans Olex Handbook 2017, page 67 (2 core V-90 PVC), copper, in air at 40 °C",
                     "product_code": ""}
    assert (by[7]["insulation"], by[229]["insulation"], by[231]["insulation"]) == ("XLPE", "", "")
    assert by[14]["code"] == "Vendor - Vendor - VENDOR - VENDOR" and by[14]["voltage"] == "VENDOR"
    assert by[7]["description"] == "Cu-XLPE-PVC-X90 (Power)" and by[37]["code"] == "AC_415V - Power - 6C+E - 4"
    assert (by[76]["description"], by[77]["description"]) == (
        "Cu-V90RPPVC-OvScn-V90RPPVC (Instrolex Pairs)", "Cu-V90RPPVC-InOvScn-V90RPPVC (Instrolex Pairs)")
    assert by[96]["code"] == "AC_240V - Power Flex - 2C+E - 25" and by[164]["description"] == "Flex-Cu-XLPE-TPE-X110 (Flex Power)"
    assert by[229]["code"] == "Earth - BARE - Bare - 120" and by[234]["description"] == "Loose Tube - SM, LSZH Jacket"
    assert by[238] | {"id": ""} == {"id": "", "code": "Network - Ethernet - CAT6A - Outdoor", "application": "Network",
                                    "type": "Ethernet", "cores": "CAT6A", "diameter": "Outdoor", "voltage": "N/A", "insulation": "",
                                    "description": "Cu-HDPE-SF/UTP CAT6 Outdoor", "sort": 238,
                                    "conductor_mm2": None, "ampacity": {}, "ampacity_source": "", "product_code": ""}
    assert not {31, 36, 38, 51, 62, 133, 235, 236} & set(by)  # the original list's blank rows


def test_edit_rules_defaults_conflicts_and_log(data_dir: Path) -> None:
    items = client.get(URL).json()["items"]
    ann = client.get(URL, headers=ANN).headers["ETag"]
    bob = client.get(URL, headers=BOB).headers["ETag"]
    mine = items[:3] + [{"id": "n1", "code": " SPECIAL - 1 ", "application": "AC_415V", "sort": "500"}]
    saved = client.put(URL, json={"items": mine}, headers={**ANN, "If-Match": ann})
    assert saved.status_code == 200, saved.text
    assert saved.json()["items"][3] == {"id": "n1", "code": "SPECIAL - 1", "application": "AC_415V", "type": "", "cores": "",
                                        "diameter": "", "voltage": "", "insulation": "", "description": "", "sort": 500,
                                        "conductor_mm2": None, "ampacity": {}, "ampacity_source": "", "product_code": ""}
    bad = client.put(URL, json={"items": mine + [{"id": "x1", "code": "special  - 1", "sort": "abc"}, {"id": "x2", "code": " "}]})
    assert bad.status_code == 422 and set(bad.json()["fields"]) == {"x1.code", "x1.sort", "x2.code"}
    stale = client.put(URL, json={"items": []}, headers={**BOB, "If-Match": bob})
    assert stale.status_code == 409 and stale.json()["changed_by"] == "ACME\\ann"

    storage.configure(data_dir)
    assert len(client.get(URL).json()["items"]) == 4  # the saved list, not the defaults again
    back = client.post(f"{URL}/defaults").json()["items"]
    assert len(back) == 657 and back[3]["code"] == "SPECIAL - 1"
    assert len(client.post(f"{URL}/defaults").json()["items"]) == 657  # nothing more to add
    log = client.get("/api/audit", params={"entity": "cable_types", "record_id": "cable-types"}).json()
    entries = log["entries"] if isinstance(log, dict) else log
    assert entries[0]["label"] == "Cable Types"
    assert any(c["new"] == "653 default cable type(s) added" for c in entries[0]["changes"])


def test_insulation_is_saved_and_read_from_descriptions_of_older_lists(data_dir: Path) -> None:
    items = client.get(URL).json()["items"][:2]
    items[0]["insulation"] = " EPR "
    assert client.put(URL, json={"items": items}).json()["items"][0]["insulation"] == "EPR"
    # a list saved before the column existed: the insulation comes from the descriptions
    old = {"items": [{"id": "o1", "code": "A", "description": "Cu-XLPE-PVC-X90 (Power)"}, {"id": "o2", "code": "B", "description": "Bare"}]}
    db = storage.get_store()._db
    with db:
        db.execute("UPDATE key_lists SET data = ? WHERE id = 'cable-types'", (json.dumps(old),))
    assert [i["insulation"] for i in client.get(URL).json()["items"]] == ["XLPE", ""]
