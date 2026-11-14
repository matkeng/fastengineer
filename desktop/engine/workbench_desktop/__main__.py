# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Sidecar entry point.

Tauri starts this with ``--port <free port> --parent-pid <tauri pid>``. The
parent-pid watchdog makes sure the engine never outlives the desktop app,
even if the process is orphaned (e.g. Nuitka onefile bootstrap is killed but
its extracted child is not).
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import threading
import time


def _ensure_std_streams() -> None:
    # With no console (windowed build / CREATE_NO_WINDOW) stdout/stderr can be
    # None, which breaks uvicorn's logging. Send them to a log file instead.
    if sys.stdout is None or sys.stderr is None:
        log_path = os.path.join(tempfile.gettempdir(), "workbench-engine.log")
        stream = open(log_path, "a", buffering=1, encoding="utf-8")  # noqa: SIM115
        if sys.stdout is None:
            sys.stdout = stream
        if sys.stderr is None:
            sys.stderr = stream


def log_config(folder) -> dict:
    """uvicorn's logging, also written to <data folder>/logs/engine.log (1 MB, 3 old files
    kept). The engine's output is otherwise lost: the installed app has no console."""
    import copy

    from uvicorn.config import LOGGING_CONFIG

    folder.mkdir(parents=True, exist_ok=True)
    cfg = copy.deepcopy(LOGGING_CONFIG)
    cfg["formatters"]["file"] = {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}
    cfg["handlers"]["file"] = {"class": "logging.handlers.RotatingFileHandler", "formatter": "file",
                               "filename": str(folder / "engine.log"), "maxBytes": 1_000_000,
                               "backupCount": 3, "encoding": "utf-8"}
    cfg["loggers"]["uvicorn"]["handlers"].append("file")  # start-up, and errors with their traceback
    cfg["loggers"]["uvicorn.access"]["handlers"].append("file")
    cfg["loggers"]["workbench_desktop"] = {"handlers": ["default", "file"], "level": "INFO", "propagate": False}
    return cfg


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        SYNCHRONIZE = 0x00100000
        WAIT_TIMEOUT = 0x00000102
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

        handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if not handle:
            return False
        try:
            return kernel32.WaitForSingleObject(handle, 0) == WAIT_TIMEOUT
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _watch_parent(pid: int, interval: float = 1.0) -> None:
    def loop() -> None:
        # Nothing here may stop the exit: once the app has gone, the engine's output (a pipe
        # to the app) is closed, so even printing can fail.
        try:
            while _pid_alive(pid):
                time.sleep(interval)
            try:
                print(f"[engine] parent {pid} exited; shutting down", flush=True)
            except Exception:  # noqa: BLE001
                pass
        finally:
            os._exit(0)

    threading.Thread(target=loop, name="parent-watchdog", daemon=True).start()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="workbench-engine")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--parent-pid", type=int, default=None)
    parser.add_argument("--data-dir", default=None, help="where saved imports are kept (workbench.db)")
    parser.add_argument("--server", action="store_true",
                        help="shared server for several users: every change must name its user "
                             "(use with --host 0.0.0.0 and a --data-dir on a local disk)")
    parser.add_argument("--admin", action="append", default=[], metavar="USER",
                        help="with --server: a user who may create projects and choose their members, "
                             "e.g. --admin ACME\\jsmith (repeat for more)")
    args = parser.parse_args(argv)

    _ensure_std_streams()
    if args.parent_pid:
        _watch_parent(args.parent_pid)

    # Import late so `--help` is instant and stream fixes apply first.
    import uvicorn

    from workbench_desktop.app import app
    from pathlib import Path

    from workbench_desktop.storage import configure

    from workbench_desktop import identity

    from workbench_desktop import projects

    identity.server_mode = args.server
    identity.admins = {projects.user_key(a) for a in args.admin if a.strip()}
    if args.server:
        print("[engine] server mode: changes are logged under the user each desktop app reports", flush=True)
        if identity.admins:
            print(f"[engine] administrators: {', '.join(sorted(identity.admins))}", flush=True)
        else:
            print("[engine] no --admin given: nobody can create projects or set members, "
                  "and every project is open to everyone", flush=True)
    configure(Path(args.data_dir) if args.data_dir else None)
    reg = projects.registry()
    print(f"[engine] data: {reg.root}", flush=True)
    for p in reg.all():
        print(f"[engine] project '{p['name']}'{' (archived)' if p['archived'] else ''}: {p['folder']}", flush=True)

    logs = reg.root / "logs"
    print(f"[engine] log: {logs / 'engine.log'}", flush=True)
    print(f"[engine] listening on http://{args.host}:{args.port}", flush=True)
    # Pass the app object (not an import string) and pin loop/http so the
    # compiled binary doesn't depend on uvicorn's dynamic "auto" imports.
    uvicorn.run(app, host=args.host, port=args.port, loop="asyncio", http="h11",
                ws="none", lifespan="on", log_level="info", log_config=log_config(logs))


if __name__ == "__main__":
    main()
