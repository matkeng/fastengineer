# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Backing a project up to one file and restoring it as a new project."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from workbench_desktop import identity, projects, storage
from workbench_desktop.app import app

client = TestClient(app)
ANN, BOB = "ACME\\ann", "ACME\\bob"


def who(user: str, project: str | None = None) -> dict[str, str]:
    h = {"X-Workbench-User": user, "X-Workbench-Machine": "PC"}
    return {**h, "X-Workbench-Project": project} if project else h


@pytest.fixture(autouse=True)
def data_dir(tmp_path: Path):
    identity.server_mode, identity.admins = False, set()
    storage.configure(tmp_path / "data")
    yield tmp_path / "data"
    storage.close()
    identity.server_mode, identity.admins = False, set()


def _project(name: str) -> dict:
    p = client.post("/api/projects", json={"name": name}, headers=who(ANN)).json()
    assert client.post("/api/ref/enums", json={"name": "Voltage"}, headers=who(ANN, p["id"])).status_code == 200
    folder = Path(p["folder"])  # the files a project keeps beside its database
    (folder / "symbols" / "doc1").mkdir(parents=True)
    (folder / "symbols" / "doc1" / "source.pdf").write_bytes(b"%PDF-drawing")
    (folder / "keylists" / "load-types").mkdir(parents=True)
    (folder / "keylists" / "load-types" / "lt1.pdf").write_bytes(b"%PDF-load-type")
    (folder / "keylists" / "load-types" / "lt2.pdf.part").write_bytes(b"half written")
    return p


def _enums(project: str) -> list[str]:
    return sorted(e["name"] for e in client.get("/api/ref", headers=who(ANN, project)).json()["enums"])


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_a_backup_holds_the_whole_project_and_restores_as_a_new_one(tmp_path: Path) -> None:
    p = _project("Plant A")
    out = client.post(f"/api/projects/{p['id']}/backup", json={"path": str(tmp_path / "plant-a")}, headers=who(ANN)).json()
    file = Path(out["path"])
    assert file.name == "plant-a.zip" and file.exists()
    with zipfile.ZipFile(file) as zf:
        assert sorted(zf.namelist()) == ["keylists/load-types/lt1.pdf", "manifest.json", "symbols/doc1/source.pdf", "workbench.db"]
        manifest = json.loads(zf.read("manifest.json"))
    assert (manifest["format"], manifest["version"], manifest["project_id"], manifest["project_name"]) == (
        "ecg-source-list-backup", 1, p["id"], "Plant A")

    # the original moves on after the backup was made
    client.post("/api/ref/enums", json={"name": "Later"}, headers=who(ANN, p["id"]))
    r = client.post("/api/projects/restore", content=file.read_bytes(), headers=who(ANN))
    assert r.status_code == 200, r.text
    new = r.json()
    assert new["id"] != p["id"] and new["name"].startswith("Plant A (restored ") and new["archived"] is False
    assert Path(new["folder"]).parent == Path(p["folder"]).parent and new["folder"] != p["folder"]
    assert _enums(new["id"]) == ["Voltage"] and _enums(p["id"]) == ["Later", "Voltage"]  # as it was; the original is untouched
    assert (Path(new["folder"]) / "symbols" / "doc1" / "source.pdf").read_bytes() == b"%PDF-drawing"
    assert (Path(new["folder"]) / "keylists" / "load-types" / "lt1.pdf").read_bytes() == b"%PDF-load-type"
    # restoring again, or under a name of your own, never collides
    again = client.post("/api/projects/restore", content=file.read_bytes(), headers=who(ANN)).json()
    assert again["name"] == new["name"] + " 2" and again["id"] not in (p["id"], new["id"])
    named = client.post("/api/projects/restore", params={"name": "Plant A"}, content=file.read_bytes(), headers=who(ANN)).json()
    assert named["name"] == "Plant A 2"
    # it is there after a restart, and the change log says where it came from
    storage.configure(Path(p["folder"]).parent.parent)
    assert new["name"] in [x["name"] for x in client.get("/api/projects/all", headers=who(ANN)).json()["projects"]]
    notes = [c["new"] for e in client.get("/api/audit", params={"entity": "project"}, headers=who(ANN, new["id"])).json()["entries"]
             for c in e["changes"] if c["path"] == "(note)"]
    assert any(n.startswith("restored from a backup of 'Plant A' made ") for n in notes)


def test_the_default_projects_backup_leaves_the_engines_own_files_out(data_dir: Path) -> None:
    client.post("/api/ref/enums", json={"name": "Voltage"}, headers=who(ANN))
    _project("Other")  # lives in <data dir>/projects, inside the Default project's folder
    sent = client.post("/api/projects/default/backup", json={}, headers=who(ANN))
    assert sent.status_code == 200 and sent.headers["content-type"] == "application/zip"
    assert "Default%20backup%20" in sent.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(sent.content)) as zf:
        assert sorted(zf.namelist()) == ["manifest.json", "workbench.db"]


def test_only_a_backup_the_app_made_is_restored(data_dir: Path) -> None:
    p = _project("Plant A")
    good = client.post(f"/api/projects/{p['id']}/backup", json={}, headers=who(ANN)).content
    with zipfile.ZipFile(io.BytesIO(good)) as zf:
        files = {n: zf.read(n) for n in zf.namelist()}
    before = sorted(x.name for x in (data_dir / "projects").iterdir())

    def refused(data: bytes) -> str:
        r = client.post("/api/projects/restore", content=data, headers=who(ANN))
        assert r.status_code == 422, r.text
        return r.json()["detail"]

    assert "not a zip file" in refused(b"hello")
    assert "no manifest" in refused(_zip({"workbench.db": files["workbench.db"]}))
    assert "not a backup the app made" in refused(_zip(files | {"manifest.json": b'{"format": "something else"}'}))
    assert "newer version" in refused(_zip(files | {"manifest.json": json.dumps({"format": "ecg-source-list-backup", "version": 99}).encode()}))
    for bad in ("../evil.txt", "symbols/../../evil.txt", "/etc/evil", "C:/evil", "other/file.txt", "engine.db", "symbols\\evil"):
        assert "it holds" in refused(_zip(files | {bad: b"x"})), bad
    assert "no project database" in refused(_zip({"manifest.json": files["manifest.json"]}))
    assert "can't be read" in refused(_zip(files | {"workbench.db": b"not a database"}))
    assert client.post("/api/projects/restore", content=b"", headers=who(ANN)).status_code == 400
    # nothing was left behind by any of them
    assert sorted(x.name for x in (data_dir / "projects").iterdir()) == before
    assert not list(data_dir.parent.rglob("evil*"))


def test_on_a_shared_server_only_an_administrator_and_never_to_the_servers_disk(tmp_path: Path) -> None:
    p = _project("Plant A")
    identity.server_mode, identity.admins = True, {projects.user_key(ANN)}
    assert client.post(f"/api/projects/{p['id']}/backup", json={}, headers=who(BOB)).status_code == 403
    assert client.post("/api/projects/restore", content=b"x", headers=who(BOB)).status_code == 403
    to_disk = client.post(f"/api/projects/{p['id']}/backup", json={"path": str(tmp_path / "x.zip")}, headers=who(ANN))
    assert to_disk.status_code == 403 and not (tmp_path / "x.zip").exists()
    sent = client.post(f"/api/projects/{p['id']}/backup", json={}, headers=who(ANN))
    assert sent.status_code == 200 and zipfile.is_zipfile(io.BytesIO(sent.content))
    restored = client.post("/api/projects/restore", content=sent.content, headers=who(ANN))
    assert restored.status_code == 200 and restored.json()["created_by"] == ANN
