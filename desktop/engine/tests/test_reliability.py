# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
from __future__ import annotations

import json
import logging
import logging.config
from pathlib import Path

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from workbench_desktop import storage
from workbench_desktop.__main__ import log_config
from workbench_desktop.app import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def data_dir(tmp_path: Path):
    storage.configure(tmp_path)
    yield tmp_path
    storage.close()


def test_work_cut_short_is_reported_when_the_project_is_next_opened(data_dir: Path) -> None:
    db = storage.get_store()._db
    with db:
        for rid, status in (("r1", "running"), ("r2", "queued"), ("r3", "done")):
            db.execute("INSERT INTO sym_runs (id, info, created_at) VALUES (?, ?, ?)",
                       (rid, json.dumps({"id": rid, "doc_ids": [], "status": status}), f"2026-01-0{rid[1]}T00:00:00+00:00"))
    storage.configure(data_dir)  # the app starts again
    runs = {r["id"]: r for r in client.get("/api/symbols/runs").json()}
    assert runs["r1"]["status"] == runs["r2"]["status"] == "error"
    assert runs["r1"]["error"] == "The app closed before this run finished. Run it again."
    assert runs["r3"]["status"] == "done" and runs["r3"]["error"] is None


def test_a_record_that_has_gone_is_a_404_not_a_500() -> None:
    router = APIRouter()

    @router.get("/api/test-gone")
    def gone():
        raise storage.NotFound("x")

    app.include_router(router)
    r = TestClient(app, raise_server_exceptions=False).get("/api/test-gone")
    assert r.status_code == 404 and r.json() == {"detail": "That record no longer exists."}


def test_the_engine_writes_a_log_file(tmp_path: Path) -> None:
    logging.config.dictConfig(log_config(tmp_path / "logs"))
    try:
        logging.getLogger("workbench_desktop.symbols_api").error("Detection run %s failed", "r1")
        logging.getLogger("uvicorn.error").info("started")
        for h in logging.getLogger("uvicorn").handlers + logging.getLogger("workbench_desktop").handlers:
            h.flush()
        text = (tmp_path / "logs" / "engine.log").read_text(encoding="utf-8")
        assert "ERROR workbench_desktop.symbols_api: Detection run r1 failed" in text and "uvicorn.error: started" in text
    finally:
        for name in ("uvicorn", "uvicorn.access", "workbench_desktop"):
            lg = logging.getLogger(name)
            for h in list(lg.handlers):
                lg.removeHandler(h)
                h.close()
            lg.propagate = True
