# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from workbench_desktop import identity, storage
from workbench_desktop.app import app

client = TestClient(app)

ANN = {"X-Workbench-User": "ACME\\ann", "X-Workbench-Machine": "PC-01"}
BOB = {"X-Workbench-User": "ACME\\bob", "X-Workbench-Machine": "PC-02"}


@pytest.fixture(autouse=True)
def data_dir(tmp_path: Path):
    storage.configure(tmp_path)
    identity.server_mode = False
    yield tmp_path
    identity.server_mode = False


def log(**params) -> list[dict]:
    return client.get("/api/audit", params=params).json()["entries"]


def test_who_changed_what_and_when() -> None:
    e = client.post("/api/ref/enums", json={"name": "Voltage"}, headers=ANN).json()
    url = f"/api/ref/enums/{e['id']}"
    items = [{"code": "LV", "value": "400", "description": "Low voltage"}]
    saved = client.put(url, json={"name": "Voltage", "items": items}, headers=BOB).json()
    saved["items"][0]["description"] = "Low voltage (<1 kV)"
    client.put(url, json={"name": "Voltages", "items": saved["items"]}, headers=ANN)
    client.delete(url, headers=BOB)

    entries = log(entity="ref_enum", record_id=e["id"])
    assert [(x["action"], x["user"], x["machine"]) for x in entries] == [
        ("delete", "ACME\\bob", "PC-02"), ("update", "ACME\\ann", "PC-01"),
        ("update", "ACME\\bob", "PC-02"), ("create", "ACME\\ann", "PC-01")]
    assert all(x["at"] and x["entity_label"] == "list" for x in entries)
    # the second update: old and new value of each changed field, and nothing else
    changes = {c["path"]: (c["old"], c["new"]) for c in entries[1]["changes"]}
    assert changes == {"name": ("Voltage", "Voltages"),
                       "items[LV].description": ("Low voltage", "Low voltage (<1 kV)")}
    # the name is kept so the log still reads well after the record is gone
    assert entries[0]["label"] == "Voltages"
    # filters
    assert {x["user"] for x in log(user="bob")} == {"ACME\\bob"}
    assert client.get("/api/audit/filters").json()["users"] == ["ACME\\ann", "ACME\\bob"]


def test_saving_without_changes_is_not_logged() -> None:
    e = client.post("/api/ref/enums", json={"name": "Voltage"}, headers=ANN).json()
    client.put(f"/api/ref/enums/{e['id']}", json={"name": "Voltage", "items": []}, headers=BOB)
    assert [x["action"] for x in log(record_id=e["id"])] == ["create"]


def test_stale_save_is_refused() -> None:
    e = client.post("/api/ref/enums", json={"name": "Voltage"}, headers=ANN).json()
    url = f"/api/ref/enums/{e['id']}"
    # both open the list
    ann_tag = client.get(url, headers=ANN).headers["etag"]
    bob_tag = client.get(url, headers=BOB).headers["etag"]
    assert ann_tag == bob_tag
    # Ann saves first
    r = client.put(url, json={"name": "Voltage A", "items": []}, headers={**ANN, "If-Match": ann_tag})
    assert r.status_code == 200 and r.headers["etag"] != ann_tag
    ann_tag = r.headers["etag"]
    # Bob's save was made against the old version: refused, and he is told who changed it
    r = client.put(url, json={"name": "Voltage B", "items": []}, headers={**BOB, "If-Match": bob_tag})
    assert r.status_code == 409
    assert r.json()["changed_by"] == "ACME\\ann" and "ACME\\ann" in r.json()["detail"]
    assert client.get(url).json()["name"] == "Voltage A"
    # ... the same for a delete
    assert client.delete(url, headers={**BOB, "If-Match": bob_tag}).status_code == 409
    # after reloading he can save
    bob_tag = client.get(url, headers=BOB).headers["etag"]
    assert client.put(url, json={"name": "Voltage B", "items": []},
                      headers={**BOB, "If-Match": bob_tag}).status_code == 200
    # Ann's next save uses the tag her own save returned, which Bob has since overtaken
    assert client.put(url, json={"name": "Voltage C", "items": []},
                      headers={**ANN, "If-Match": ann_tag}).status_code == 409
    # a client's own earlier change never conflicts with itself
    stale = client.get(url, headers=BOB).headers["etag"]
    client.put(url, json={"name": "Voltage D", "items": []}, headers=BOB)
    assert client.put(url, json={"name": "Voltage E", "items": []},
                      headers={**BOB, "If-Match": stale}).status_code == 200


def test_rows_conflict_by_the_time_last_seen() -> None:
    t = client.post("/api/ref/tables", json={"name": "Cables"}, headers=ANN).json()
    tid = t["id"]
    detail = client.put(f"/api/ref/tables/{tid}", headers=ANN, json={
        "name": "Cables", "columns": [{"name": "Tag", "type": "text"}]}).json()
    col = detail["table"]["columns"][0]["id"]
    row = client.post(f"/api/ref/tables/{tid}/rows", json={"values": {col: "C-1"}}, headers=ANN).json()
    url = f"/api/ref/tables/{tid}/rows/{row['id']}"
    seen = {"X-Workbench-Base-Time": row["updated_at"]}

    assert client.put(url, json={"values": {col: "C-2"}}, headers={**ANN, **seen}).status_code == 200
    r = client.put(url, json={"values": {col: "C-3"}}, headers={**BOB, **seen})
    assert r.status_code == 409 and r.json()["changed_by"] == "ACME\\ann"
    assert client.delete(url, headers={**BOB, **seen}).status_code == 409

    entries = log(entity="ref_table", record_id=tid, children=True)
    rows = [x for x in entries if x["entity"] == "ref_row"]
    assert [(x["action"], x["label"], x["parent_id"]) for x in rows] == [
        ("update", "Cables: row", tid), ("create", "Cables: row", tid)]
    assert rows[0]["changes"] == [{"path": f"values.{col}", "old": "C-1", "new": "C-2"}]


def test_server_mode_needs_a_user() -> None:
    identity.server_mode = True
    assert client.post("/api/ref/enums", json={"name": "Voltage"}).status_code == 401
    assert client.get("/api/ref").status_code == 200  # reading is not logged, so it needs no name
    assert client.post("/api/ref/enums", json={"name": "Voltage"}, headers=ANN).status_code == 200
    who = client.get("/api/whoami", headers=ANN).json()
    assert who["user"] == "ACME\\ann" and who["machine"] == "PC-01" and who["server"] is True


def test_standalone_uses_the_local_login() -> None:
    e = client.post("/api/ref/enums", json={"name": "Voltage"}).json()
    (entry,) = log(record_id=e["id"])
    assert entry["user"] == identity.local_user() and entry["machine"] == identity.local_machine()
