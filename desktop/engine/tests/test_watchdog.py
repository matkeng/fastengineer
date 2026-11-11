# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
from __future__ import annotations

import threading

from workbench_desktop import __main__ as entry


class _Closed:
    """The engine's output once the app has gone: every write fails."""

    def write(self, _text: str) -> int:
        raise OSError(22, "Invalid argument")

    def flush(self) -> None:
        raise OSError(22, "Invalid argument")


def _run_watchdog(monkeypatch, alive) -> list[int]:
    exited: list[int] = []
    done = threading.Event()
    monkeypatch.setattr(entry, "_pid_alive", alive)
    monkeypatch.setattr(entry.os, "_exit", lambda code: (exited.append(code), done.set()))
    entry._watch_parent(12345, interval=0.01)
    assert done.wait(5), "the watchdog never exited"
    return exited


def test_the_engine_exits_when_the_app_has_gone_even_if_it_cannot_print(monkeypatch) -> None:
    monkeypatch.setattr(entry.sys, "stdout", _Closed())
    assert _run_watchdog(monkeypatch, lambda pid: False) == [0]


def test_the_engine_exits_if_the_check_itself_fails(monkeypatch) -> None:
    def broken(pid: int) -> bool:
        raise OSError("no such process")
    assert _run_watchdog(monkeypatch, broken) == [0]
