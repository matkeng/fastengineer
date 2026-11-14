# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
from __future__ import annotations

import base64
import io
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
    """The example library, with the text scan switched on (it is off in a new library)."""
    libs = client.get(f"{API}/libraries").json()
    assert len(libs) == 1, libs
    assert libs[0]["pattern_scan"] is False
    res = client.put(f"{API}/libraries/{libs[0]['id']}", json={**libs[0], "pattern_scan": True})
    assert res.status_code == 200, res.text
    return client.get(f"{API}/libraries").json()[0]


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

    # PID Symbols: one row per detection, with its centre in mm, into the master list
    psl = client.post("/api/mel/recipes", json={"name": "P&ID symbols", "target": "PSL"}).json()
    rev = client.post(f"/api/mel/recipes/{psl['id']}/revisions/symbols", json={"run_id": run["id"]})
    assert rev.status_code == 200, rev.text and rev.json()["key_header"] == "Key"
    detail = client.get(f"/api/mel/recipes/{psl['id']}").json()
    assert detail["output_name"] == "PID Symbols" and "x_mm" in detail["fields"]
    mapped = {m["field"]: m["column"] for m in detail["recipe"]["mapping"]}
    assert mapped["tag"] == "Tag" and mapped["x_mm"] == "X (mm)" and mapped["y_mm"] == "Y (mm)" and mapped["loop"] == "loop"
    pid = client.get("/api/pid-symbols").json()
    assert pid["sources"][0]["name"] == "P&ID symbols" and pid["rows"] and {"tag", "x_mm", "y_mm", "drawing", "page"} <= set(pid["fields"])
    page1 = client.get(f"{API}/drawings/{d['id']}/pages/1/result").json()
    s0 = page1["symbols"][0]
    row = next(r for r in pid["rows"] if r["page"] == 1 and r["symbol"] == s0["template_desc"]
               and abs(r["x_mm"] - (s0["box"][0] + s0["box"][2]) / 2 * 25.4 / 200) < 0.06)
    assert abs(row["y_mm"] - (s0["box"][1] + s0["box"][3]) / 2 * 25.4 / 200) < 0.06 and row["source"] == "template"
    assert isinstance(row["x_mm"], float) and row["drawing"] == "pid-sample.pdf"
    assert len(pid["rows"]) == rev.json()["num_rows"] == client.get("/api/keylists").json()["pid_symbols"]["items"]
    assert len(pid["rows"]) >= sum(len(client.get(f"{API}/drawings/{d['id']}/pages/{n}/result").json()["symbols"]) for n in (1, 2))
    book = load_workbook(io.BytesIO(client.post("/api/list-workbooks/pid-symbols/export", json={}).content))
    assert [c.value for c in book["PID Symbols"][1]][:2] == ["Import", "Tag"]
    # the Loops view: by loop number, with its tags, functions and drawings, a suggested type, chosen and verified
    loops = client.get("/api/pid-symbols/loops").json()
    by_loop = {x["loop"]: x for x in loops["loops"]}
    assert [x["loop"] for x in loops["loops"]] == sorted(by_loop, key=int)
    l1023 = by_loop["1023"]
    assert {"FT-1023", "FV-1023"} <= set(l1023["tags"]) and {"FT", "FV"} <= set(l1023["functions"])
    assert "pid-sample.pdf p1" in l1023["drawings"] and l1023["type_name"] == "Flow Transmitter" and l1023["type_by"] == "auto"
    valve = next(t for t in loops["types"] if t["name"] == "Flow Control Valve")
    changed = client.put("/api/pid-symbols/loops/1023", json={"type_id": valve["id"], "verified": True}).json()
    assert (changed["type_name"], changed["type_by"], changed["verified"]) == ("Flow Control Valve", "user", True) and changed["verified_by"]
    assert client.put("/api/pid-symbols/loops/1023", json={"verified": False}).json()["type_name"] == "Flow Control Valve"
    back = client.put("/api/pid-symbols/loops/1023", json={"type_id": None}).json()
    assert (back["type_name"], back["type_by"], back["verified"]) == ("Flow Transmitter", "auto", False)
    assert client.put("/api/pid-symbols/loops/1023", json={"type_id": ""}).json()["type_id"] is None
    assert client.put("/api/pid-symbols/loops/1023", json={"type_id": "nope"}).status_code == 422
    assert client.put("/api/pid-symbols/loops/424242", json={"verified": True}).status_code == 404
    log = client.get("/api/audit", params={"entity": "pid_loops", "record_id": "1023"}).json()
    assert len(log["entries"] if isinstance(log, dict) else log) >= 4
    # the Load List and the PIL import are untouched by it
    assert all(r["source"] != "P&ID symbols" for r in client.get("/api/loadlist").json()["rows"])


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


def test_review_false_positives_and_missed_symbols(data_dir: Path) -> None:
    lib = _example()
    d = _upload(lib["id"])
    run = _wait(f"{API}/runs/{client.post(f'{API}/runs', json={'doc_ids': [d['id']]}).json()['id']}")
    assert run["tag_count"] == 11
    sheets = client.get(f"{API}/runs/{run['id']}/sheets").json()
    assert [(s["doc_id"], s["page"]) for s in sheets] == [(d["id"], 1), (d["id"], 2)]
    page = client.get(f"{API}/runs/{run['id']}/sheets/{d['id']}/1").json()
    sym = next(s for s in page["symbols"] if s["tag"] == "PT-1025")
    url = f"{API}/drawings/{d['id']}/pages/1/review"
    tags = lambda: {r["Tag"] for r in client.get(f"{API}/runs/{run['id']}/tags").json()["rows"]}  # noqa: E731

    # Reject a symbol: its tag leaves the run's tags list (and the export), and it's kept for undo.
    res = client.post(url, json={"action": "reject", "kind": "symbol", "box": sym["box"],
                                 "template_id": sym["template_id"], "run_id": run["id"]})
    assert res.status_code == 200, res.text
    body = res.json()
    assert [s["tag"] for s in body["result"]["rejected_symbols"]] == ["PT-1025"]
    assert "PT-1025" not in tags()
    assert client.get(f"{API}/runs/{run['id']}").json()["tag_count"] == 10
    assert client.get(url).json()["rejected"][0]["kind"] == "symbol"
    xlsx = client.post(f"{API}/runs/{run['id']}/export", json={"format": "xlsx"})
    assert load_workbook(io.BytesIO(xlsx.content))["Tags"].max_row == 11

    # Re-analysing the page keeps the correction.
    again = client.post(f"{API}/drawings/{d['id']}/pages/1/analyse").json()
    assert "PT-1025" not in {t["tag"] for t in again["tags"]} and len(again["rejected_symbols"]) == 1

    # Restore brings it back.
    client.post(url, json={"action": "restore", "kind": "symbol", "box": sym["box"], "run_id": run["id"]})
    assert "PT-1025" in tags()

    # A missed symbol: reject it, then add it back by clicking near its centre (snapped).
    client.post(url, json={"action": "reject", "kind": "symbol", "box": sym["box"], "template_id": sym["template_id"]})
    cx, cy = (sym["box"][0] + sym["box"][2]) / 2 + 6, (sym["box"][1] + sym["box"][3]) / 2 - 5
    added = client.post(url, json={"action": "add", "template_id": sym["template_id"], "x": cx, "y": cy,
                                   "run_id": run["id"]}).json()
    assert added["symbol"]["tag"] == "PT-1025"
    assert not added["review"]["rejected"]  # adding on a rejected symbol just restores it
    # Clear the stored correction, then add as a genuinely manual symbol with a typed tag.
    client.put(f"{API}/drawings/{d['id']}/pages/1/overrides/{sym['template_id']}",
               json={"template_id": sym["template_id"], "ignore": True})
    page = client.post(f"{API}/drawings/{d['id']}/pages/1/analyse").json()
    assert not any(s["template_id"] == sym["template_id"] for s in page["symbols"])
    added = client.post(url, json={"action": "add", "template_id": sym["template_id"], "x": cx, "y": cy}).json()
    s = added["symbol"]
    assert s["origin"] == "manual" and s["tag"] == "PT-1025"
    ix = max(0, min(s["box"][2], sym["box"][2]) - max(s["box"][0], sym["box"][0]))
    iy = max(0, min(s["box"][3], sym["box"][3]) - max(s["box"][1], sym["box"][1]))
    area = (sym["box"][2] - sym["box"][0]) * (sym["box"][3] - sym["box"][1])
    assert ix * iy / area > 0.8
    assert client.post(url, json={"action": "add", "template_id": sym["template_id"], "x": cx, "y": cy}).status_code == 422
    typed = client.post(url, json={"action": "tag", "box": s["box"], "tag": "PT-9999"}).json()
    assert "PT-9999" in {t["tag"] for t in typed["result"]["tags"]}
    page = client.post(f"{API}/drawings/{d['id']}/pages/1/analyse").json()
    assert any(x["origin"] == "manual" and x["tag"] == "PT-9999" for x in page["symbols"])
    # Rejecting a hand-added symbol removes it.
    gone = client.post(url, json={"action": "reject", "kind": "symbol", "box": s["box"]}).json()
    assert not gone["review"]["added"] and not any(x["origin"] == "manual" for x in gone["result"]["symbols"])

    # Text-scan tags can be rejected too.
    p1 = client.get(f"{API}/runs/{run['id']}/sheets/{d['id']}/1").json()
    scan = next(t for t in p1["tags"] if t["source"] == "pattern")
    assert scan["tag"] == "PSV-1040"
    r = client.post(url, json={"action": "reject", "kind": "tag", "box": scan["box"], "tag": scan["tag"],
                               "run_id": run["id"]}).json()
    assert [t["tag"] for t in r["result"]["rejected_tags"]] == ["PSV-1040"]
    assert "PSV-1040" not in tags()
    client.post(url, json={"action": "restore", "kind": "tag", "box": scan["box"], "run_id": run["id"]})
    assert "PSV-1040" in tags()

    assert client.post(url, json={"action": "add"}).status_code == 422
    other = client.post(f"{API}/libraries", json={"name": "Other", "copy_from": lib["id"]}).json()
    foreign = client.get(f"{API}/templates", params={"library_id": other["id"]}).json()[0]
    assert client.post(url, json={"action": "add", "template_id": foreign["id"], "x": cx, "y": cy}).status_code == 422


def test_template_preview_matches_the_template_created(data_dir: Path) -> None:
    lib = _example()
    d = _upload(lib["id"])
    res = client.post(f"{API}/drawings/{d['id']}/pages/1/analyse").json()
    b = next(s for s in res["symbols"] if s["tag"] == "PT-1025")["box"]
    drag = [b[0] - 20, b[1] - 20, b[2] + 20, b[3] + 20]
    pv = client.post(f"{API}/templates/preview", json={"doc_id": d["id"], "page": 1, "rect": drag})
    assert pv.status_code == 200, pv.text
    pv = pv.json()
    assert drag[0] <= pv["rect"][0] and pv["rect"][2] <= drag[2] and drag[1] <= pv["rect"][1] and pv["rect"][3] <= drag[3]
    assert pv["width"] < drag[2] - drag[0]  # trimmed
    assert base64.b64decode(pv["png"])[:4] == b"\x89PNG"
    t = client.post(f"{API}/templates/from-page", json={"doc_id": d["id"], "page": 1, "rect": drag, "desc": "Copy"}).json()
    assert (t["width"], t["height"]) == (pv["width"], pv["height"])
    loose = client.post(f"{API}/templates/preview", json={"doc_id": d["id"], "page": 1, "rect": drag, "trim": False}).json()
    assert loose["width"] == round(drag[2] - drag[0])
    blank = client.post(f"{API}/templates/preview", json={"doc_id": d["id"], "page": 1, "rect": [5, 5, 60, 60]})
    assert blank.status_code == 400 and "linework" in blank.json()["detail"]


def _gray_png(data: bytes):
    return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE)


def test_a_template_cut_from_a_page_keeps_a_view_with_its_text(data_dir: Path) -> None:
    lib = _example()
    d = _upload(lib["id"])
    res = client.post(f"{API}/drawings/{d['id']}/pages/1/analyse").json()
    b = next(s for s in res["symbols"] if s["tag"] == "PT-1025")["box"]
    drag = [b[0] - 20, b[1] - 20, b[2] + 20, b[3] + 20]
    pv = client.post(f"{API}/templates/preview", json={"doc_id": d["id"], "page": 1, "rect": drag}).json()
    assert {w["text"] for w in pv["words"]} >= {"PT"} and base64.b64decode(pv["view_png"])[:4] == b"\x89PNG"
    t = client.post(f"{API}/templates/from-page", json={"doc_id": d["id"], "page": 1, "rect": drag, "desc": "Copy"}).json()

    image = _gray_png(client.get(f"{API}/templates/{t['id']}/image.png").content)
    view = _gray_png(client.get(f"{API}/templates/{t['id']}/view.png").content)
    assert image.shape == view.shape == (t["height"], t["width"])
    words = client.get(f"{API}/templates/{t['id']}/words").json()
    assert words == pv["words"] and {w["text"] for w in words} >= {"PT", "1025"}
    for w in words:  # in template pixels, inside the template: the text is there in the view, erased in the image
        x1, y1, x2, y2 = (int(round(v)) for v in w["box"])
        assert 0 <= x1 < x2 <= t["width"] and 0 <= y1 < y2 <= t["height"]
        assert view[y1:y2, x1:x2].min() < 128 and image[y1:y2, x1:x2].min() > 200, w

    # moved to another library, or copied with it, the view goes along; deleting the template removes it
    other = client.post(f"{API}/libraries", json={"name": "Copies", "copy_from": lib["id"]}).json()
    copy = next(c for c in client.get(f"{API}/templates", params={"library_id": other["id"]}).json() if c["desc"] == "Copy")
    assert client.get(f"{API}/templates/{copy['id']}/words").json() == words
    moved = client.put(f"{API}/templates/{t['id']}", json={**t, "library_id": other["id"]})
    assert moved.status_code == 200, moved.text
    assert client.get(f"{API}/templates/{t['id']}/words").json() == words
    assert client.delete(f"{API}/templates/{t['id']}").status_code in (200, 204)
    assert client.get(f"{API}/templates/{t['id']}/words").status_code == 404
    st = storage.get_symbols()
    assert st._db.execute("SELECT COUNT(*) FROM sym_template_views WHERE template_id = ?", (t["id"],)).fetchone()[0] == 0

    # a template with no view (the example's, uploaded) shows its own image and no text
    plain = client.get(f"{API}/templates", params={"library_id": lib["id"]}).json()[0]
    assert client.get(f"{API}/templates/{plain['id']}/words").json() == []
    assert client.get(f"{API}/templates/{plain['id']}/view.png").content == client.get(f"{API}/templates/{plain['id']}/image.png").content
