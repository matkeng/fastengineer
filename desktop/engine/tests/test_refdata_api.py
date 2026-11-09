from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from workbench_desktop import storage
from workbench_desktop.app import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def data_dir(tmp_path: Path):
    storage.configure(tmp_path)
    yield tmp_path


def test_lists_tables_rows(data_dir: Path) -> None:
    e = client.post("/api/ref/enums", json={"name": "Voltage"}).json()
    # Names are unique across lists and tables, ignoring case.
    dup = client.post("/api/ref/tables", json={"name": "voltage "})
    assert dup.status_code == 422 and dup.json()["fields"] == {"name": "Name already used"}

    items = [{"code": "LV", "value": "400 V", "description": "Low voltage"}, {"code": "HV", "value": "11 kV"}]
    e = client.put(f"/api/ref/enums/{e['id']}", json={"name": "Voltage", "items": items}).json()
    lv, hv = e["items"][0]["id"], e["items"][1]["id"]
    bad = client.put(f"/api/ref/enums/{e['id']}", json={"name": "Voltage", "items": items + [{"code": "lv", "value": "x"}]})
    assert bad.status_code == 422 and any(k.endswith(".code") for k in bad.json()["fields"])

    t = client.post("/api/ref/tables", json={"name": "Motors"}).json()
    cols = [{"name": "Tag", "type": "text", "required": True, "unique": True},
            {"name": "kW", "type": "decimal"}, {"name": "Voltage", "type": "enum", "enum_id": e["id"]}]
    d = client.put(f"/api/ref/tables/{t['id']}", json={"name": "Motors", "columns": cols}).json()
    tag, kw, volt = (c["id"] for c in d["table"]["columns"])
    assert d["enums"][e["id"]]["name"] == "Voltage"

    r1 = client.post(f"/api/ref/tables/{t['id']}/rows", json={"values": {tag: "P-1", kw: "30", volt: lv}}).json()
    r2 = client.post(f"/api/ref/tables/{t['id']}/rows", json={"values": {tag: "P-2", kw: "7.50", volt: "HV"}}).json()
    assert r2["values"] == {tag: "P-2", kw: "7.5", volt: hv}
    clash = client.post(f"/api/ref/tables/{t['id']}/rows", json={"values": {tag: "p-1"}})
    assert clash.status_code == 422 and tag in clash.json()["fields"]
    upd = client.put(f"/api/ref/tables/{t['id']}/rows/{r1['id']}", json={"values": {tag: "P-1", kw: "37", volt: lv}})
    assert upd.json()["values"][kw] == "37"

    # A used item and a used list can't be deleted.
    res = client.put(f"/api/ref/enums/{e['id']}", json={"name": "Voltage", "items": [items[1] | {"id": hv}]})
    assert res.status_code == 422 and "LV (1 row)" in res.json()["detail"]
    assert client.delete(f"/api/ref/enums/{e['id']}").status_code == 422

    # Type change converts existing rows (decimal -> text), or is refused without saving.
    cols2 = [{**c, "id": i} for c, i in zip(cols, (tag, kw, volt))]
    cols2[1]["type"] = "integer"
    bad = client.put(f"/api/ref/tables/{t['id']}", json={"name": "Motors", "columns": cols2})
    assert bad.status_code == 422 and "7.5" in bad.json()["fields"][kw]
    assert client.get(f"/api/ref/tables/{t['id']}").json()["table"]["columns"][1]["type"] == "decimal"  # unchanged
    cols2[1]["type"] = "text"
    cols2[2] = {**cols2[2], "type": "text", "enum_id": None}
    d = client.put(f"/api/ref/tables/{t['id']}", json={"name": "Motor list", "columns": cols2}).json()
    assert {r["values"][volt] for r in d["rows"]} == {"LV", "HV"}  # enum items became their codes

    # Persisted across a restart.
    storage.configure(data_dir)
    ov = client.get("/api/ref").json()
    assert ov["tables"][0] == {"id": t["id"], "name": "Motor list", "description": "", "columns": 3, "rows": 2}
    assert ov["enums"][0]["used_by"] == []
    assert client.delete(f"/api/ref/tables/{t['id']}/rows/{r2['id']}").status_code == 200
    assert client.delete(f"/api/ref/enums/{e['id']}").status_code == 200
    assert client.delete(f"/api/ref/tables/{t['id']}").status_code == 200
    assert client.get("/api/ref").json()["tables"] == []
    assert client.post("/api/ref/tables", json={"name": "Voltage"}).status_code == 200  # name free again
