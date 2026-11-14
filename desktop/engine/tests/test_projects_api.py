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


def sql(path: Path, script: str) -> None:
    """Change a database file directly, and let go of it (Windows keeps an open file locked)."""
    import sqlite3
    from contextlib import closing
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript(script)


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
    storage.close()                                        # the engine is stopped for the upgrade
    (old / "engine.db").unlink()                           # as if upgrading from before projects
    sql(old / "workbench.db", "DELETE FROM settings WHERE key = 'project'")
    storage.configure(old)
    assert lists(BOB, "default") == ["Voltage"]
    assert client.get("/api/ref", headers=who(CAT)).status_code == 403


def test_each_project_has_its_own_data_and_change_log(server: Path) -> None:
    a, b = new_project("Plant A", members=[BOB]), new_project("Plant B", members=[BOB])
    assert Path(a["folder"]) == server / "projects" / "Plant A"   # a folder you can recognise
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
    first = client.get("/api/audit", headers=B).json()["entries"][-2:]       # the project's own log starts with these
    assert [x["label"] for x in first] == ["Standards copied from 'Plant A'", "Plant B"]
    # afterwards the two are independent
    client.put(f"/api/ref/enums/{e['id']}", headers=B, json={"name": "Voltage B", "items": []})
    assert lists(BOB, a["id"]) == ["Voltage"] and lists(BOB, b["id"]) == ["Voltage B"]


def test_a_project_in_a_folder_of_its_own(server: Path, tmp_path: Path) -> None:
    folder = tmp_path / "elsewhere" / "Plant C"
    c = new_project("Plant C", path=str(folder), members=[BOB])
    client.post("/api/ref/enums", json={"name": "Voltage"}, headers=who(BOB, c["id"]))
    assert Path(c["folder"]) == folder and (folder / "workbench.db").exists()
    assert not (server / "projects" / "Plant C").exists() and c["external"] is True
    # the same folder can't be used twice; shares and relative paths are refused
    for bad in (str(folder), "\\\\server\\share\\x", "//server/share/x", "relative/folder"):
        r = client.post("/api/projects", json={"name": "Other", "path": bad}, headers=who(ANN))
        assert r.status_code == 422 and "path" in r.json()["fields"], bad
    # after a restart the engine still serves it
    storage.configure(server)
    assert lists(BOB, c["id"]) == ["Voltage"]


def attach(path: Path) -> dict:
    r = client.post("/api/projects/attach", json={"path": str(path)}, headers=who(ANN))
    assert r.status_code == 200, r.text
    return r.json()


def test_a_project_folder_is_complete_on_its_own(server: Path, tmp_path: Path) -> None:
    import shutil
    a = new_project("Plant A", members=[BOB])
    client.post("/api/ref/enums", json={"name": "Voltage"}, headers=who(BOB, a["id"]))
    client.put(f"/api/projects/{a['id']}", json={"members": [BOB, CAT]}, headers=who(ANN))
    storage.configure(server)                                  # everything is saved in the folder

    # Another engine (another server or PC) opens a copy of the folder: the name, the
    # members, the data and the history all come with it. Nothing else is needed.
    moved = tmp_path / "usb" / "Plant A"
    shutil.copytree(a["folder"], moved)
    storage.configure(tmp_path / "other-server")
    p = attach(moved)
    assert (p["id"], p["name"], p["members"], p["external"]) == (a["id"], "Plant A", [BOB, CAT], True)
    assert lists(CAT, p["id"]) == ["Voltage"]
    log = client.get("/api/audit", headers=who(CAT, p["id"])).json()["entries"]
    assert [(e["entity"], e["action"], e["user"]) for e in log] == [
        ("project", "update", ANN), ("ref_enum", "create", BOB), ("project", "create", ANN)]
    assert log[0]["changes"] == [{"path": "members", "old": [BOB], "new": [BOB, CAT]}]
    # there is no project in an empty folder
    assert client.post("/api/projects/attach", json={"path": str(tmp_path / "usb")}, headers=who(ANN)).status_code == 422

    # Taking it off the list leaves the folder alone, and it can be added again.
    assert client.delete(f"/api/projects/{p['id']}", headers=who(ANN)).status_code == 200
    assert client.get("/api/ref", headers=who(CAT, p["id"])).status_code == 404
    assert (moved / "workbench.db").exists()
    assert attach(moved)["id"] == a["id"]
    # the engine's own projects can't be taken off the list, only archived
    assert client.delete("/api/projects/default", headers=who(ANN)).status_code == 422
    assert client.delete(f"/api/projects/{p['id']}", headers=who(BOB)).status_code == 403


def test_a_copy_beside_the_original_is_a_project_of_its_own(server: Path, tmp_path: Path) -> None:
    import shutil
    a = new_project("Plant A", members=[BOB])
    client.post("/api/ref/enums", json={"name": "Voltage"}, headers=who(BOB, a["id"]))
    storage.configure(server)
    shutil.copytree(a["folder"], tmp_path / "Plant A copy")
    storage.configure(server)
    b = attach(tmp_path / "Plant A copy")
    assert b["id"] != a["id"] and b["members"] == [BOB]
    client.post("/api/ref/enums", json={"name": "Pressure"}, headers=who(BOB, b["id"]))
    assert lists(BOB, a["id"]) == ["Voltage"] and lists(BOB, b["id"]) == ["Pressure", "Voltage"]
    storage.configure(server)                                  # and it keeps its new identity
    assert {p["id"] for p in client.get("/api/projects/all", headers=who(ANN)).json()["projects"]} == {
        "default", a["id"], b["id"]}


def test_folders_dropped_in_or_gone_missing(server: Path, tmp_path: Path) -> None:
    import shutil
    outside = new_project("Plant X", path=str(tmp_path / "x"), members=[BOB])
    inside = new_project("Plant Y")
    storage.close()                                            # the engine is stopped while folders are moved
    # a project folder put into <data dir>/projects is found at the next start, with no other step
    shutil.copytree(inside["folder"], server / "projects" / "Restored")
    # a pointed-at folder that has gone (moved, disk not connected) is reported, not an error
    shutil.move(str(tmp_path / "x"), str(tmp_path / "moved"))
    storage.configure(server)
    listing = client.get("/api/projects/all", headers=who(ANN)).json()
    assert sorted(p["name"] for p in listing["projects"]) == ["Default", "Plant Y", "Plant Y"]
    assert listing["missing"] == [str(tmp_path / "x")]
    assert client.get("/api/ref", headers=who(BOB, outside["id"])).status_code == 404
    # point the engine at where it went, and forget the old place
    assert attach(tmp_path / "moved")["id"] == outside["id"]
    after = client.post("/api/projects/forget", json={"path": str(tmp_path / "x")}, headers=who(ANN)).json()
    assert after["missing"] == [] and client.get("/api/ref", headers=who(BOB, outside["id"])).status_code == 200


def test_takes_over_from_the_central_list_of_an_earlier_version(server: Path, tmp_path: Path) -> None:
    a = new_project("Plant A", members=[BOB])
    client.post("/api/ref/enums", json={"name": "Voltage"}, headers=who(BOB, a["id"]))
    storage.close()
    # Put things back the way the earlier version kept them: details in registry.db, folder named by id.
    folder = server / "projects" / "0123abcd"
    Path(a["folder"]).rename(folder)
    sql(folder / "workbench.db", "DELETE FROM settings WHERE key = 'project'")
    (server / "engine.db").unlink()
    sql(server / "registry.db", """
            CREATE TABLE projects (id TEXT PRIMARY KEY, name TEXT, name_key TEXT, path TEXT, archived INTEGER,
                                   created_at TEXT, created_by TEXT);
            CREATE TABLE members (project_id TEXT, user_key TEXT, user TEXT);
            CREATE TABLE users (user_key TEXT PRIMARY KEY, user TEXT, last_project_id TEXT, last_seen TEXT);
            INSERT INTO projects VALUES ('default', 'Default', 'default', '.', 0, '2026-11-01T00:00:00+00:00', 'system');
            INSERT INTO projects VALUES ('0123abcd', 'Plant A', 'plant a', '', 0, '2026-11-02T00:00:00+00:00', 'ACME\\ann');
            INSERT INTO members VALUES ('0123abcd', 'acme\\cat', 'ACME\\cat');
            INSERT INTO users VALUES ('acme\\cat', 'ACME\\cat', '0123abcd', '2026-11-03T00:00:00+00:00');
        """)
    storage.configure(server)
    mine = client.get("/api/projects", headers=who(CAT)).json()
    assert mine["projects"] == [{"id": "0123abcd", "name": "Plant A", "archived": False}] and mine["current"] == "0123abcd"
    assert lists(CAT, "0123abcd") == ["Voltage"]
    assert not (server / "registry.db").exists()               # read once, then set aside
    storage.configure(server)                                  # now the folder itself knows
    assert client.get("/api/projects", headers=who(CAT)).json()["projects"][0]["name"] == "Plant A"


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
    new_project("Plant A", members=[BOB])
    b = new_project("Plant B", members=[BOB])
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
