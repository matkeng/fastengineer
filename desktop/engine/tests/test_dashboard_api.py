# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("cv2")
pytest.importorskip("pypdfium2")

from workbench_desktop import storage, symbols_api  # noqa: E402
from workbench_desktop.app import app  # noqa: E402

SAMPLES = Path(__file__).resolve().parents[3] / "samples"
client = TestClient(app)


@pytest.fixture(autouse=True)
def data_dir(tmp_path: Path, monkeypatch):
    storage.configure(tmp_path)
    monkeypatch.setattr(symbols_api, "ocr_provider", lambda: (None, "not available in tests"))
    yield tmp_path


def _wait(path: str):
    for _ in range(600):
        body = client.get(path).json()
        if body["status"] not in ("rendering", "queued", "running"):
            return body
        time.sleep(0.1)
    raise AssertionError(path)


def test_empty_dashboard_has_the_example_library(data_dir: Path) -> None:
    d = client.get("/api/dashboard").json()
    c = d["counts"]
    assert (c["libraries"], c["templates"], c["drawings"], c["recipes"], c["tables"]) == (1, 3, 0, 0, 0)
    assert c["latest_tags"] is None and d["runs"] == [] and d["recent"] == []
    assert d["storage"]["data_dir"] == str(data_dir) and d["storage"]["ocr_available"] is False


def test_dashboard_counts_recent_and_runs(data_dir: Path) -> None:
    r = client.post("/api/mel/recipes", json={"name": "Plant MEL", "target": "MEL"}).json()
    client.post(f"/api/mel/recipes/{r['id']}/revisions/csv", params={"filename": "mel-sample.csv", "key": "Equipment Tag"},
                content=(SAMPLES / "mel-sample.csv").read_bytes())
    t = client.post("/api/ref/tables", json={"name": "Motors"}).json()
    tree = client.post("/api/ref/trees", json={"name": "Areas"}).json()
    lib = client.get("/api/symbols/libraries").json()[0]
    lib = client.put(f"/api/symbols/libraries/{lib['id']}", json={**lib, "pattern_scan": True}).json()  # off in a new library
    dw = client.post("/api/symbols/drawings", params={"filename": "pid-sample.pdf", "library_id": lib["id"]},
                     content=(SAMPLES / "pid-sample.pdf").read_bytes()).json()
    dw = _wait(f"/api/symbols/drawings/{dw['id']}")
    d = client.get("/api/dashboard").json()
    assert d["counts"]["pages_unanalysed"] == 2
    run = _wait(f"/api/symbols/runs/{client.post('/api/symbols/runs', json={'doc_ids': [dw['id']]}).json()['id']}")

    d = client.get("/api/dashboard").json()
    c = d["counts"]
    assert (c["recipes"], c["revisions"], c["tables"], c["drawings"], c["pages"], c["pages_unanalysed"]) == (1, 1, 1, 1, 2, 0)
    assert c["latest_tags"] == 11 and c["runs"] == 1
    assert d["runs"] == [{"id": run["id"], "at": d["runs"][0]["at"], "template": 10, "text_scan": 1, "status": "done"}]
    kinds = [e["kind"] for e in d["recent"]]
    assert kinds[0] == "run" and {"drawing", "revision", "recipe", "table", "tree"} <= set(kinds)
    assert c["trees"] == 1 and next(e for e in d["recent"] if e["kind"] == "tree")["id"] == tree["id"]
    times = [e["at"] for e in d["recent"]]
    assert times == sorted(times, reverse=True)
    table_ev = next(e for e in d["recent"] if e["kind"] == "table")
    assert table_ev["id"] == t["id"] and table_ev["section"] == "ref"
    assert d["storage"]["page_images"] == 2 and d["storage"]["drawings_bytes"] > 0 and d["storage"]["database_bytes"] > 0
