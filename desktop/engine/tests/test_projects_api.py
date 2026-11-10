# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from workbench_desktop import identity, projects, storage
from workbench_desktop.app import app

client = TestClient(app)


def who(user: str, project: str | None = None) -> dict[str, str]:
    h = {"X-Workbench-User": user, "X-Workbench-Machine": "PC"}
    return {**h, "X-Workbench-Project": project} if project else h


ANN, BOB, CAT = "ACME\\ann", "ACME\\bob", "ACME\\cat"  # Ann is the administrator


@pytest.fixture(autouse=True)
def data_dir(tmp_path: Path):
    identity.server_mode, identity.admins = False, set()
    storage.configure(tmp_path / "data")
    yield tmp_path / "data"
    identity.server_mode, identity.admins = False, set()


@pytest.fixture
def server(data_dir: Path):
    identity.server_mode, identity.admins = True, {projects.user_key(ANN)}
    return data_dir


def new_project(name: str, **body) -> dict:
    r = client.post("/api/projects", json={"name": name, **body}, headers=who(ANN))
    assert r.status_code == 200, r.text
    return r.json()


def lists(user: str, project: str) -> list[str]:
    r = client.get("/api/ref", headers=who(user, project))
    assert r.status_code == 200, r.text
    return sorted(e["name"] for e in r.json()["enums"])


def test_existing_data_becomes_the_default_project(data_dir: Path) -> None:
    client.post("/api/ref/enums", json={"name": "Voltage"})
    assert (data_dir / "workbench.db").exists()           # where it always was
    storage.configure(data_dir)                            # restart
    mine = client.get("/api/projects").json()
    assert [p["name"] for p in mine["projects"]] == ["Default"] and mine["current"] == "default"
    assert mine["is_admin"] is True and mine["enforced"] is False   # your own PC: you manage it
    assert lists("me", "default") == ["Voltage"]


def test_upgrading_a_server_keeps_its_users_in(tmp_path: Path) -> None:
    old = tmp_path / "old"
    storage.configure(old)
    client.post("/api/ref/enums", json={"name": "Voltage"}, headers=who(BOB))
    identity.server_mode, identity.admins = True, {projects.user_key(ANN)}
    (old / "registry.db").unlink()                         # as if upgrading from before projects
    storage.configure(old)
    assert lists(BOB, "default") == ["Voltage"]
    assert client.get("/api/ref", headers=who(CAT)).status_code == 403


def test_each_project_has_its_own_data_and_change_log(server: Path) -> None:
    a, b = new_project("Plant A", members=[BOB]), new_project("Plant B", members=[BOB])
    assert Path(a["folder"]) == server / "projects" / a["id"]
    client.post("/api/ref/enums", json={"name": "Voltage"}, headers=who(BOB, a["id"]))
    client.post("/api/ref/enums", json={"name": "Voltage"}, headers=who(BOB, b["id"]))   # same name: no clash
    client.post("/api/ref/enums", json={"name": "Pressure"}, headers=who(BOB, b["id"]))
    assert lists(BOB, a["id"]) == ["Voltage"] and lists(BOB, b["id"]) == ["Pressure", "Voltage"]
    assert (Path(a["folder"]) / "workbench.db").exists() and (Path(b["folder"]) / "workbench.db").exists()
    log = lambda p: client.get("/api/audit", params={"entity": "ref_enum"}, headers=who(BOB, p)).json()["entries"]
    assert len(log(a["id"])) == 1 and len(log(b["id"])) == 2


def test_members_only(server: Path) -> None:
    a, b = new_project("Plant A", members=[BOB]), new_project("Plant B", members=[CAT])
    names = lambda user: [p["name"] for p in client.get("/api/projects", headers=who(user)).json()["projects"]]
    assert names(BOB) == ["Plant A"] and names(CAT) == ["Plant B"]
    assert names(ANN) == ["Default", "Plant A", "Plant B"]             # administrators see everything
    r = client.get("/api/ref", headers=who(BOB, b["id"]))
    assert r.status_code == 403 and "not a member" in r.json()["detail"]
    assert client.post("/api/ref/enums", json={"name": "X"}, headers=who(BOB, b["id"])).status_code == 403
    assert client.post(f"/api/projects/{b['id']}/open", headers=who(BOB)).status_code == 403
    # user names are not case sensitive
    assert client.get("/api/ref", headers=who("acme\\BOB", a["id"])).status_code == 200
    # someone in no project is told so, and can still ask which projects they have
    dan = client.get("/api/ref", headers=who("ACME\\dan"))
    assert dan.status_code == 403 and "not been added to a project" in dan.json()["detail"]
    assert client.get("/api/projects", headers=who("ACME\\dan")).json() == {
        "projects": [], "current": None, "is_admin": False, "enforced": True}
    # ... and the administrator then finds them in the list of people to add
    assert "ACME\\dan" in client.get("/api/projects/all", headers=who(ANN)).json()["users"]
    r = client.put(f"/api/projects/{b['id']}", json={"members": [CAT, "ACME\\dan"]}, headers=who(ANN))
    assert r.json()["members"] == [CAT, "ACME\\dan"]
    assert client.get("/api/ref", headers=who("ACME\\dan")).status_code == 200


def test_only_administrators_manage_projects(server: Path) -> None:
    a = new_project("Plant A", members=[BOB])
    assert client.post("/api/projects", json={"name": "Mine"}, headers=who(BOB)).status_code == 403
    assert client.put(f"/api/projects/{a['id']}", json={"members": [BOB, CAT]}, headers=who(BOB)).status_code == 403
    assert client.get("/api/projects/all", headers=who(BOB)).status_code == 403
    # names are unique, ignoring case
    dup = client.post("/api/projects", json={"name": "plant a"}, headers=who(ANN))
    assert dup.status_code == 422 and "name" in dup.json()["fields"]
    # rename, archive
    client.put(f"/api/projects/{a['id']}", json={"name": "Plant Alpha"}, headers=who(ANN))
    client.put(f"/api/projects/{a['id']}", json={"archived": True}, headers=who(ANN))
    assert client.get("/api/projects", headers=who(BOB)).json()["projects"] == []
    r = client.get("/api/ref", headers=who(BOB, a["id"]))
    assert r.status_code == 403 and "archived" in r.json()["detail"]
    assert (Path(a["folder"]) / "workbench.db").exists()   # archiving deletes nothing
    client.put(f"/api/projects/{a['id']}", json={"archived": False}, headers=who(ANN))
    assert [p["name"] for p in client.get("/api/projects", headers=who(BOB)).json()["projects"]] == ["Plant Alpha"]
    # every one of those changes is on record
    log = client.get("/api/projects/log", headers=who(ANN)).json()
    assert [(e["action"], e["user"], e["label"]) for e in log] == [
        ("update", ANN, "Plant Alpha"), ("update", ANN, "Plant Alpha"), ("update", ANN, "Plant Alpha"),
        ("create", ANN, "Plant A")]
    assert log[2]["changes"] == [{"path": "name", "old": "Plant A", "new": "Plant Alpha"}]


def test_without_administrators_every_project_is_open(data_dir: Path) -> None:
    identity.server_mode = True
    assert client.post("/api/ref/enums", json={"name": "Voltage"}, headers=who(BOB)).status_code == 200
    assert client.post("/api/projects", json={"name": "Mine"}, headers=who(BOB)).status_code == 403


def test_copying_standards_into_a_new_project(server: Path) -> None:
    a = new_project("Plant A", members=[BOB])
    A = who(BOB, a["id"])
    e = client.post("/api/ref/enums", json={"name": "Voltage"}, headers=A).json()
    client.put(f"/api/ref/enums/{e['id']}", headers=A, json={"name": "Voltage", "items": [{"code": "LV", "value": "400"}]})
    t = client.post("/api/ref/tables", json={"name": "Cables"}, headers=A).json()
    d = client.put(f"/api/ref/tables/{t['id']}", headers=A, json={"name": "Cables", "columns": [{"name": "Tag"}]}).json()
    col = d["table"]["columns"][0]["id"]
    client.post(f"/api/ref/tables/{t['id']}/rows", json={"values": {col: "C-1"}}, headers=A)
    libs_a = client.get("/api/symbols/libraries", headers=A).json()          # includes the example library
    client.post("/api/mel/recipes", json={"name": "Motors", "target": "mel"}, headers=A)   # work, not a standard

    b = new_project("Plant B", copy_from=a["id"], members=[BOB])
    B = who(BOB, b["id"])
    assert lists(BOB, b["id"]) == ["Voltage"]
    assert client.get(f"/api/ref/enums/{e['id']}", headers=B).json()["items"][0]["code"] == "LV"
    assert [r["values"][col] for r in client.get(f"/api/ref/tables/{t['id']}", headers=B).json()["rows"]] == ["C-1"]
    libs_b = client.get("/api/symbols/libraries", headers=B).json()
    assert [(x["name"], x["templates"]) for x in libs_b] == [(x["name"], x["templates"]) for x in libs_a]
    assert len(libs_b) == 1                                                   # the example was not added twice
    assert client.get("/api/mel/recipes", headers=B).json() == []             # the work stayed behind
    assert client.get("/api/audit", headers=B).json()["entries"][-1]["label"] == "Standards copied from 'Plant A'"
    # afterwards the two are independent
    client.put(f"/api/ref/enums/{e['id']}", headers=B, json={"name": "Voltage B", "items": []})
    assert lists(BOB, a["id"]) == ["Voltage"] and lists(BOB, b["id"]) == ["Voltage B"]


def test_a_project_in_a_folder_of_its_own(server: Path, tmp_path: Path) -> None:
    folder = tmp_path / "elsewhere" / "Plant C"
    c = new_project("Plant C", path=str(folder), members=[BOB])
    client.post("/api/ref/enums", json={"name": "Voltage"}, headers=who(BOB, c["id"]))
    assert Path(c["folder"]) == folder and (folder / "workbench.db").exists()
    assert not (server / "projects" / c["id"]).exists()
    # the same folder can't be used twice; shares and relative paths are refused
    for bad in (str(folder), "\\\\server\\share\\x", "//server/share/x", "relative/folder"):
        r = client.post("/api/projects", json={"name": "Other", "path": bad}, headers=who(ANN))
        assert r.status_code == 422 and "path" in r.json()["fields"], bad
    # a folder that already holds a project database is opened as it is
    storage.configure(tmp_path / "second")
    d = new_project("Plant C again", path=str(folder))
    assert lists(ANN, d["id"]) == ["Voltage"]
    r = client.post("/api/projects", json={"name": "Copy", "path": str(folder), "copy_from": d["id"]}, headers=who(ANN))
    assert r.status_code == 422


def test_starts_in_the_project_last_opened(server: Path) -> None:
    a, b = new_project("Plant A", members=[BOB, CAT]), new_project("Plant B", members=[BOB, CAT])
    current = lambda user: client.get("/api/projects", headers=who(user)).json()["current"]
    assert current(BOB) == a["id"]                                            # first, until one is opened
    client.post(f"/api/projects/{b['id']}/open", headers=who(BOB))
    assert current(BOB) == b["id"] and current(CAT) == a["id"]                # remembered per user
    # a request that names no project works in that one
    client.post("/api/ref/enums", json={"name": "Voltage"}, headers=who(BOB))
    assert lists(BOB, b["id"]) == ["Voltage"] and lists(BOB, a["id"]) == []
    me = client.get("/api/whoami", headers=who(BOB)).json()
    assert me["project"] == {"id": b["id"], "name": "Plant B"} and me["is_admin"] is False
    # if it is taken away, they fall back to one they still have
    client.put(f"/api/projects/{b['id']}", json={"members": [CAT]}, headers=who(ANN))
    assert current(BOB) == a["id"]


def test_background_work_stays_in_its_project(server: Path) -> None:
    a, b = new_project("Plant A", members=[BOB]), new_project("Plant B", members=[BOB])
    seen = {}

    def job():
        seen["user"] = identity.current().user
        seen["path"] = storage.get_store().path

    token = identity._current.set(identity.RequestContext(BOB, "PC", project=b["id"]))
    try:
        carried = identity.carry(job)
    finally:
        identity._current.reset(token)
    carried()   # later, on the worker thread, outside any request
    assert seen == {"user": BOB, "path": Path(b["folder"]) / "workbench.db"}
