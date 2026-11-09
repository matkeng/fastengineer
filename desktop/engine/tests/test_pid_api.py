from __future__ import annotations

import io
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

pytest.importorskip("fitz")
pytest.importorskip("cv2")

from workbench_desktop import pid_api, storage  # noqa: E402
from workbench_desktop.app import app  # noqa: E402

SAMPLES = Path(__file__).resolve().parents[3] / "samples"
client = TestClient(app)


@pytest.fixture(autouse=True)
def data_dir(tmp_path: Path, monkeypatch):
    storage.configure(tmp_path)
    monkeypatch.setattr(pid_api, "ocr_provider", lambda: (None, "not available in tests"))
    yield tmp_path


def _wait(path: str, done=lambda b: b["status"] not in ("rendering", "queued", "running"), timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        body = client.get(path).json()
        if done(body):
            return body
        time.sleep(0.1)
    raise AssertionError(f"timed out waiting for {path}: {body}")


def _upload(name: str = "pid-sample.pdf") -> dict:
    res = client.post("/api/pid/drawings", params={"filename": name}, content=(SAMPLES / name).read_bytes())
    assert res.status_code == 200, res.text
    return _wait(f"/api/pid/drawings/{res.json()['id']}")


def _import_library() -> list[dict]:
    res = client.post("/api/pid/templates/import", json=json.loads((SAMPLES / "pid-templates.json").read_text()))
    assert res.status_code == 200, res.text
    return res.json()


def test_pid_flow_into_an_instrument_list(data_dir: Path) -> None:
    d = _upload()
    assert d["status"] == "ready" and [p["rotation"] for p in d["pages"]] == [0, 90]
    assert (data_dir / "pid" / d["id"] / "page-2.png").exists()
    png = client.get(f"/api/pid/drawings/{d['id']}/pages/1/image.png")
    assert png.headers["content-type"] == "image/png" and png.content[:4] == b"\x89PNG"

    lib = _import_library()
    assert [t["desc"] for t in lib] == ["Instrument bubble", "Control valve", "Valve"]
    assert [t["priority"] for t in lib] == [0, 1, 2]
    assert client.get("/api/pid/settings").json()["exclusions"]["PID/FIR"]["areas"]

    run = client.post("/api/pid/runs", json={"doc_ids": [d["id"]]}).json()
    assert run["total_steps"] == 2
    run = _wait(f"/api/pid/runs/{run['id']}")
    assert run["status"] == "done" and run["tag_count"] == 11, run
    tags = client.get(f"/api/pid/runs/{run['id']}/tags").json()
    assert {r["Tag"] for r in tags["rows"]} >= {"FT-1023", "TT-1026A", "PSV-1040", "FV-2001"}

    result = client.get(f"/api/pid/drawings/{d['id']}/pages/1/result").json()
    assert sum(s["template_desc"] == "Valve" for s in result["symbols"]) == 2

    xlsx = client.post(f"/api/pid/runs/{run['id']}/export", json={"format": "xlsx"})
    assert load_workbook(io.BytesIO(xlsx.content))["P&ID tags"].max_row == 12
    saved = client.post(f"/api/pid/runs/{run['id']}/export", json={"format": "csv", "path": str(data_dir / "tags")})
    assert Path(saved.json()["path"]).name == "tags.csv"
    assert client.post(f"/api/pid/runs/{run['id']}/export", content=b"{}",
                       headers={"content-type": "text/plain"}).status_code in (415, 422)  # never written

    # -> list import (target PIL) -> instrument list
    recipe = client.post("/api/mel/recipes", json={"name": "Instruments", "target": "PIL"}).json()
    rev = client.post(f"/api/mel/recipes/{recipe['id']}/revisions/pid", json={"run_id": run["id"]})
    assert rev.status_code == 200, rev.text
    assert rev.json()["num_rows"] == 11 and rev.json()["key_header"] == "Tag"
    detail = client.get(f"/api/mel/recipes/{recipe['id']}").json()
    assert detail["output_name"] == "Instrument list" and "instrument_type" in detail["fields"]
    r = detail["recipe"]
    r["text_columns"] = [{"name": "Status", "value": "New"}]
    r["mapping"] = [{"field": "tag", "column": "Tag"}, {"field": "function", "column": "Function"},
                    {"field": "loop", "column": "Loop"}, {"field": "pid_drawing", "column": "Drawings"},
                    {"field": "status", "column": "Status"}]
    assert client.put(f"/api/mel/recipes/{recipe['id']}", json=r).status_code == 200
    il = client.post(f"/api/mel/recipes/{recipe['id']}/loadlist", json={}).json()
    assert il["fields"] == ["tag", "function", "loop", "pid_drawing", "status"]
    row = next(x for x in il["rows"] if x["tag"] == "FT-1023")
    assert row == {"tag": "FT-1023", "function": "FT", "loop": "1023", "pid_drawing": "pid-sample.pdf", "status": "New"}
    out = client.post(f"/api/mel/recipes/{recipe['id']}/export", json={"table": "loadlist", "format": "xlsx"})
    assert load_workbook(io.BytesIO(out.content)).sheetnames[0] == "Instrument list"

    # A MEL recipe still maps onto the load list.
    mel = client.post("/api/mel/recipes", json={"name": "M", "target": "MEL"}).json()
    assert client.get(f"/api/mel/recipes/{mel['id']}").json()["output_name"] == "Load list"


def test_templates_from_page_points_test_move_and_overrides(data_dir: Path) -> None:
    d = _upload()
    # Drag a loose box around the FT-1023 bubble (sheet 1, centre 350,200 pt at 200 dpi).
    z = 200 / 72
    rect = [(350 - 22) * z, (200 - 22) * z, (350 + 22) * z, (200 + 17.5) * z]  # stops above the pipe stub
    t = client.post("/api/pid/templates/from-page", json={"doc_id": d["id"], "page": 1, "rect": rect, "desc": "Bubble"})
    assert t.status_code == 200, t.text
    t = t.json()
    assert 85 <= t["width"] <= 100 and 85 <= t["height"] <= 100  # trimmed to the circle
    w, h = t["width"], t["height"]
    t["points"] = [{"name": "Function", "x": w / 2, "y": h / 2 - 5 * z}, {"name": "Number", "x": w / 2, "y": h / 2 + 7 * z}]
    t["tag_format"] = "{Function}-{Number}"
    t["threshold"] = 0.7
    saved = client.put(f"/api/pid/templates/{t['id']}", json=t)
    assert saved.status_code == 200, saved.text

    bad = dict(t, tag_format="{Func}-{Number}", points=[*t["points"], {"name": "far", "x": 5000, "y": 1}])
    err = client.put(f"/api/pid/templates/{t['id']}", json=bad)
    assert err.status_code == 422 and set(err.json()["fields"]) == {"tag_format", "points"}

    test = client.post(f"/api/pid/templates/{t['id']}/test", json={"doc_id": d["id"], "page": 1}).json()
    assert len(test["symbols"]) == 7 and test["best"] > 0.95
    assert {s["tag"] for s in test["symbols"]} >= {"FT-1023", "LIC-1030", "PI-1041"}
    draft = dict(t, threshold=0.99)  # unsaved edit
    assert len(client.post(f"/api/pid/templates/{t['id']}/test",
                           json={"doc_id": d["id"], "page": 1, "template": draft}).json()["symbols"]) == 1

    client.put(f"/api/pid/drawings/{d['id']}/pages/1/overrides/{t['id']}", json={"template_id": t["id"], "ignore": True})
    res = client.post(f"/api/pid/drawings/{d['id']}/pages/1/analyse").json()
    assert not res["symbols"]
    client.delete(f"/api/pid/drawings/{d['id']}/pages/1/overrides/{t['id']}")
    assert len(client.post(f"/api/pid/drawings/{d['id']}/pages/1/analyse").json()["symbols"]) == 7

    lib = _import_library()
    order = [x["desc"] for x in client.get("/api/pid/templates", params={"drawing_type": "PID", "block_set": "FIR"}).json()]
    assert order == ["Bubble", "Instrument bubble", "Control valve", "Valve"]
    client.post(f"/api/pid/templates/{lib[2]['id']}/move", json={"index": 0})
    ts = client.get("/api/pid/templates", params={"drawing_type": "PID", "block_set": "FIR"}).json()
    assert [x["desc"] for x in ts] == ["Valve", "Bubble", "Instrument bubble", "Control valve"]
    assert [x["priority"] for x in ts] == [0, 1, 2, 3]
    client.delete(f"/api/pid/templates/{t['id']}")
    ts = client.get("/api/pid/templates").json()
    assert [x["priority"] for x in ts] == [0, 1, 2]
    exported = client.post("/api/pid/templates/export", json={"drawing_type": "PID", "block_set": "FIR"}).json()
    assert len(exported["templates"]) == 3 and exported["exclusions"]
    assert client.get(f"/api/pid/templates/{ts[0]['id']}/mask.png").content[:4] == b"\x89PNG"
    libs = client.get("/api/pid/libraries").json()
    assert libs == [{"drawing_type": "PID", "block_set": "FIR", "templates": 3, "drawings": 1}]


def test_scanned_pdf_without_ocr_warns_and_bad_input(data_dir: Path) -> None:
    d = _upload("pid-sample-scanned.pdf")
    assert [p["text_source"] for p in d["pages"]] == ["none", "none"]
    run = _wait(f"/api/pid/runs/{client.post('/api/pid/runs', json={'doc_ids': [d['id']]}).json()['id']}")
    assert run["status"] == "done" and run["tag_count"] == 0
    assert any("No text layer and OCR is unavailable" in w for w in run["warnings"])
    assert client.get("/api/pid/ocr").json() == {"available": False, "engine": None, "reason": "not available in tests"}

    assert client.post("/api/pid/drawings", params={"filename": "x.pdf"}, content=b"not a pdf").status_code == 400
    bad = client.put("/api/pid/settings", json={"tag_pattern": "[A-Z"})
    assert bad.status_code == 422 and "tag_pattern" in bad.json()["fields"]
    recipe = client.post("/api/mel/recipes", json={"name": "I", "target": "PIL"}).json()
    assert client.post(f"/api/mel/recipes/{recipe['id']}/revisions/pid", json={"run_id": run["id"]}).status_code == 400

    client.delete(f"/api/pid/drawings/{d['id']}")
    assert not (data_dir / "pid" / d["id"]).exists()
    assert client.get(f"/api/pid/drawings/{d['id']}").status_code == 404
