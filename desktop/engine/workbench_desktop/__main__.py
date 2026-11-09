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
        while _pid_alive(pid):
            time.sleep(interval)
        print(f"[engine] parent {pid} exited; shutting down", flush=True)
        os._exit(0)

    threading.Thread(target=loop, name="parent-watchdog", daemon=True).start()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="workbench-engine")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--parent-pid", type=int, default=None)
    parser.add_argument("--data-dir", default=None, help="where saved imports are kept (workbench.db)")
    args = parser.parse_args(argv)

    _ensure_std_streams()
    if args.parent_pid:
        _watch_parent(args.parent_pid)

    # Import late so `--help` is instant and stream fixes apply first.
    import uvicorn

    from workbench_desktop.app import app
    from pathlib import Path

    from workbench_desktop.storage import configure

    store = configure(Path(args.data_dir) if args.data_dir else None)
    print(f"[engine] data: {store.path}", flush=True)

    print(f"[engine] listening on http://{args.host}:{args.port}", flush=True)
    # Pass the app object (not an import string) and pin loop/http so the
    # compiled binary doesn't depend on uvicorn's dynamic "auto" imports.
    uvicorn.run(app, host=args.host, port=args.port, loop="asyncio", http="h11",
                ws="none", lifespan="on", log_level="info")


if __name__ == "__main__":
    main()
