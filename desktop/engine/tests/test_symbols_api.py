# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
from __future__ import annotations

import io
import json
import time
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

cv2 = pytest.importorskip("cv2")
pytest.importorskip("pypdfium2")

from workbench_desktop import storage, symbols_api  # noqa: E402
from workbench_desktop.app import app  # noqa: E402

SAMPLES = Path(__file__).resolve().parents[3] / "samples"
API = "/api/symbols"
client = TestClient(app)


@pytest.fixture(autouse=True)
def data_dir(tmp_path: Path, monkeypatch):
    storage.configure(tmp_path)
    monkeypatch.setattr(symbols_api, "ocr_provider", lambda: (None, "not available in tests"))
    yield tmp_path


def _wait(path: str, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        body = client.get(path).json()
        if body["status"] not in ("rendering", "queued", "running"):
            return body
        time.sleep(0.1)
    raise AssertionError(f"timed out waiting for {path}: {body}")


def _example() -> dict:
    libs = client.get(f"{API}/libraries").json()
    assert len(libs) == 1, libs
    return libs[0]


def _upload(library_id: str, name: str = "pid-sample.pdf") -> dict:
    res = client.post(f"{API}/drawings", params={"filename": name, "library_id": library_id},
                      content=(SAMPLES / name).read_bytes())
    assert res.status_code == 200, res.text
    return _wait(f"{API}/drawings/{res.json()['id']}")


def test_first_run_has_the_p_and_id_example(data_dir: Path) -> None:
    lib = _example()
    assert lib["name"] == "P&ID instruments (ISA)" and lib["templates"] == 3
    assert lib["columns"] == ["function", "loop", "suffix"]
    ts = client.get(f"{API}/templates", params={"library_id": lib["id"]}).json()
    assert [t["desc"] for t in ts] == ["Instrument bubble", "Control valve", "Valve"]
    # Deleting the example doesn't bring it back on the next start; "restore" does.
    assert client.delete(f"{API}/libraries/{lib['id']}").status_code == 200
    storage.configure(data_dir)
    assert client.get(f"{API}/libraries").json() == []
    assert client.post(f"{API}/libraries/restore-example").json()["name"] == "P&ID instruments (ISA)"


def test_flow_into_an_instrument_list(data_dir: Path) -> None:
    lib = _example()
    d = _upload(lib["id"])
    assert d["status"] == "ready" and [p["rotation"] for p in d["pages"]] == [0, 90]
    assert (data_dir / "symbols" / d["id"] / "page-2.png").exists()
    png = client.get(f"{API}/drawings/{d['id']}/pages/1/image.png")
    assert png.headers["content-type"] == "image/png" and png.content[:4] == b"\x89PNG"

    run = client.post(f"{API}/runs", json={"doc_ids": [d["id"]]}).json()
    assert run["total_steps"] == 2 and run["columns"] == ["function", "loop", "suffix"]
    run = _wait(f"{API}/runs/{run['id']}")
    assert run["status"] == "done" and run["tag_count"] == 11, run
    tags = client.get(f"{API}/runs/{run['id']}/tags").json()
    assert tags["headers"][:4] == ["Tag", "function", "loop", "suffix"]
    assert {r["Tag"] for r in tags["rows"]} >= {"FT-1023", "TT-1026A", "PSV-1040", "FV-2001"}
    result = client.get(f"{API}/drawings/{d['id']}/pages/1/result").json()
    assert sum(s["template_desc"] == "Valve" for s in result["symbols"]) == 2

    xlsx = client.post(f"{API}/runs/{run['id']}/export", json={"format": "xlsx"})
    assert load_workbook(io.BytesIO(xlsx.content))["Tags"].max_row == 12
    saved = client.post(f"{API}/runs/{run['id']}/export", json={"format": "csv", "path": str(data_dir / "tags")})
    assert Path(saved.json()["path"]).name == "tags.csv"
    assert client.post(f"{API}/runs/{run['id']}/export", content=b"{}",
                       headers={"content-type": "text/plain"}).status_code in (415, 422)  # never written

    recipe = client.post("/api/mel/recipes", json={"name": "Instruments", "target": "PIL"}).json()
    rev = client.post(f"/api/mel/recipes/{recipe['id']}/revisions/symbols", json={"run_id": run["id"]})
    assert rev.status_code == 200, rev.text
    assert rev.json()["num_rows"] == 11 and rev.json()["key_header"] == "Tag"
    detail = client.get(f"/api/mel/recipes/{recipe['id']}").json()
    assert detail["output_name"] == "Instrument list" and "instrument_type" in detail["fields"]
    r = detail["recipe"]
    r["text_columns"] = [{"name": "Status", "value": "New"}]
    r["mapping"] = [{"field": "tag", "column": "Tag"}, {"field": "function", "column": "function"},
                    {"field": "loop", "column": "loop"}, {"field": "pid_drawing", "column": "Drawings"},
                    {"field": "status", "column": "Status"}]
    assert client.put(f"/api/mel/recipes/{recipe['id']}", json=r).status_code == 200
    il = client.post(f"/api/mel/recipes/{recipe['id']}/loadlist", json={}).json()
    row = next(x for x in il["rows"] if x["tag"] == "FT-1023")
    assert row == {"tag": "FT-1023", "function": "FT", "loop": "1023", "pid_drawing": "pid-sample.pdf", "status": "New"}
    out = client.post(f"/api/mel/recipes/{recipe['id']}/export", json={"table": "loadlist", "format": "xlsx"})
    assert load_workbook(io.BytesIO(out.content)).sheetnames[0] == "Instrument list"
    mel = client.post("/api/mel/recipes", json={"name": "M", "target": "MEL"}).json()
    assert client.get(f"/api/mel/recipes/{mel['id']}").json()["output_name"] == "Load list"


def test_custom_library_templates_masks_and_overrides(data_dir: Path) -> None:
    example = _example()
    lib = client.post(f"{API}/libraries", json={"name": "My symbols"}).json()
    dup = client.post(f"{API}/libraries", json={"name": "my  SYMBOLS"})
    assert dup.status_code == 422
    bad = client.put(f"{API}/libraries/{lib['id']}", json={**lib, "tag_pattern": "[A-Z", "tag_format": "{x}"})
    assert bad.status_code == 422 and "tag_pattern" in bad.json()["fields"]
    bad = client.put(f"{API}/libraries/{lib['id']}", json={**lib, "tag_pattern": r"(?P<a>[A-Z]+)(?P<b>\d+)", "tag_format": "{c}"})
    assert set(bad.json()["fields"]) == {"tag_format"}
    lib = client.put(f"{API}/libraries/{lib['id']}", json={**lib, "tag_pattern": r"(?P<a>[A-Z]{2,3})(?P<b>\d{4}[A-Z]?)",
                                                         "tag_format": "{a}/{b}", "default_threshold": 0.7}).json()

    d = _upload(lib["id"])
    z = 200 / 72
    rect = [(350 - 22) * z, (200 - 22) * z, (350 + 22) * z, (200 + 17.5) * z]  # FT-1023's bubble, loose
    t = client.post(f"{API}/templates/from-page", json={"doc_id": d["id"], "page": 1, "rect": rect, "desc": "Bubble"}).json()
    assert t["library_id"] == lib["id"] and t["threshold"] == 0.7 and t["mask_mode"] == "auto"
    assert 85 <= t["width"] <= 100 and 85 <= t["height"] <= 100  # trimmed to the circle
    w, h = t["width"], t["height"]
    t["points"] = [{"name": "A", "x": w / 2, "y": h / 2 - 5 * z}, {"name": "B", "x": w / 2, "y": h / 2 + 7 * z}]
    t["tag_format"] = "{A}{B}"
    assert client.put(f"{API}/templates/{t['id']}", json=t).status_code == 200
    bad = client.put(f"{API}/templates/{t['id']}", json={**t, "tag_format": "{C}", "points": [*t["points"], {"name": "far", "x": 5000, "y": 1}]})
    assert set(bad.json()["fields"]) == {"tag_format", "points"}
    assert client.put(f"{API}/templates/{t['id']}", json={**t, "mask_mode": "custom"}).json()["fields"] == {
        "mask_mode": "Paint or upload a mask first."}

    test = client.post(f"{API}/templates/{t['id']}/test", json={"doc_id": d["id"], "page": 1}).json()
    assert len(test["symbols"]) == 7 and test["best"] > 0.95
    assert {s["tag"] for s in test["symbols"]} >= {"FT1023", "LIC1030"}

    # Custom mask: only the top quarter of the circle is compared -> still matches every bubble,
    # including with an unsaved draft mask sent with the test.
    mask = np.zeros((h, w), np.uint8)
    mask[: h // 4] = 255
    ok, buf = cv2.imencode(".png", mask)
    draft = {"doc_id": d["id"], "page": 1, "template": {**t, "mask_mode": "custom"},
             "mask_png": __import__("base64").b64encode(buf.tobytes()).decode()}
    assert len(client.post(f"{API}/templates/{t['id']}/test", json=draft).json()["symbols"]) >= 7
    saved = client.put(f"{API}/templates/{t['id']}/mask", content=buf.tobytes())
    assert saved.status_code == 200 and saved.json()["mask_mode"] == "custom" and saved.json()["has_custom_mask"]
    m = cv2.imdecode(np.frombuffer(client.get(f"{API}/templates/{t['id']}/mask.png").content, np.uint8), 0)
    assert m[: h // 4].all() and not m[h // 2:].any()
    auto = cv2.imdecode(np.frombuffer(client.get(f"{API}/templates/{t['id']}/mask.png?mode=auto").content, np.uint8), 0)
    assert auto[h // 2:].any()
    empty = client.put(f"{API}/templates/{t['id']}/mask", content=cv2.imencode(".png", np.zeros((h, w), np.uint8))[1].tobytes())
    assert empty.status_code == 400
    assert client.delete(f"{API}/templates/{t['id']}/mask").json()["mask_mode"] == "auto"
    client.put(f"{API}/templates/{t['id']}/mask", content=buf.tobytes())

    run = _wait(f"{API}/runs/{client.post(f'{API}/runs', json={'doc_ids': [d['id']]}).json()['id']}")
    rows = client.get(f"{API}/runs/{run['id']}/tags").json()
    assert rows["headers"][:3] == ["Tag", "a", "b"]
    found = {r["Tag"] for r in rows["rows"]}
    assert {"FT/1023", "TT/1026A", "LIC/1030"} <= found and "PSV/1040" not in found  # its pattern has no dash

    client.put(f"{API}/drawings/{d['id']}/pages/1/overrides/{t['id']}", json={"template_id": t["id"], "ignore": True})
    assert not client.post(f"{API}/drawings/{d['id']}/pages/1/analyse").json()["symbols"]
    client.delete(f"{API}/drawings/{d['id']}/pages/1/overrides/{t['id']}")
    assert len(client.post(f"{API}/drawings/{d['id']}/pages/1/analyse").json()["symbols"]) == 7

    # Export / import keeps templates, points and the custom mask; priorities; copy; delete rules.
    exported = client.post(f"{API}/libraries/{lib['id']}/export", json={}).json()
    assert exported["templates"][0]["mask_png"] and exported["library"]["tag_format"] == "{a}/{b}"
    again = client.post(f"{API}/libraries/import", json=exported).json()
    assert again["name"] == "My symbols (2)"
    t2 = client.get(f"{API}/templates", params={"library_id": again["id"]}).json()
    assert t2[0]["has_custom_mask"] and [(p["name"], p["x"], p["y"]) for p in t2[0]["points"]] == [(p["name"], p["x"], p["y"]) for p in t["points"]]
    copy = client.post(f"{API}/libraries", json={"name": "Copy", "copy_from": example["id"]}).json()
    ts = client.get(f"{API}/templates", params={"library_id": copy["id"]}).json()
    client.post(f"{API}/templates/{ts[2]['id']}/move", json={"index": 0})
    ts = client.get(f"{API}/templates", params={"library_id": copy["id"]}).json()
    assert [x["desc"] for x in ts] == ["Valve", "Instrument bubble", "Control valve"] and [x["priority"] for x in ts] == [0, 1, 2]
    assert client.delete(f"{API}/libraries/{lib['id']}").status_code == 409  # a drawing uses it
    assert client.post(f"{API}/libraries/import", json={"templates": []}).status_code == 400


def test_scanned_pdf_without_ocr_warns_and_bad_input(data_dir: Path) -> None:
    lib = _example()
    d = _upload(lib["id"], "pid-sample-scanned.pdf")
    assert [p["text_source"] for p in d["pages"]] == ["none", "none"]
    run = _wait(f"{API}/runs/{client.post(f'{API}/runs', json={'doc_ids': [d['id']]}).json()['id']}")
    assert run["status"] == "done" and run["tag_count"] == 0
    assert any("No text layer and OCR is unavailable" in w for w in run["warnings"])
    assert client.get(f"{API}/ocr").json() == {"available": False, "engine": None, "reason": "not available in tests"}
    assert client.post(f"{API}/drawings", params={"filename": "x.pdf", "library_id": lib["id"]},
                       content=b"not a pdf").status_code == 400
    recipe = client.post("/api/mel/recipes", json={"name": "I", "target": "PIL"}).json()
    assert client.post(f"/api/mel/recipes/{recipe['id']}/revisions/symbols", json={"run_id": run["id"]}).status_code == 400
    client.delete(f"{API}/drawings/{d['id']}")
    assert not (data_dir / "symbols" / d["id"]).exists()
    assert client.get(f"{API}/drawings/{d['id']}").status_code == 404
