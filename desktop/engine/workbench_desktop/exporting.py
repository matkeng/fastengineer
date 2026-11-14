# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Saving an export to a file the user chose in a Save As dialog.

The engine writes the file itself only on the user's own PC. A shared server never writes to
a path a client names: it would be a file on the server's disk, anywhere the service account
can write. There the client downloads the bytes and saves them itself.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException

from . import identity


def save_to(path: str, data: bytes, suffix: str) -> dict[str, str]:
    """Write `data` to `path`, with `suffix` (".xlsx") put on if it is missing. Returns the path written."""
    if identity.server_mode:
        raise HTTPException(403, "A shared server does not save files on its own disk. "
                                 "Download the export instead (leave out the path).")
    target = Path(path)
    if target.suffix.lower() != suffix:
        target = target.with_suffix(suffix)
    try:
        target.write_bytes(data)
    except OSError as exc:  # e.g. the file is open in Excel
        raise HTTPException(409, f"Could not save {target.name}: {exc.strerror or exc}. "
                                 "Is it open in another program?") from exc
    return {"path": str(target)}
