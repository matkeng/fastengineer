# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Reading an uploaded file (the raw request body) without holding more than its size limit."""

from __future__ import annotations

from fastapi import HTTPException, Request


async def read_upload(request: Request, limit: int) -> bytes:
    """The request body, refused with 413 as soon as it is known to be over `limit` bytes:
    from its Content-Length when the client sends one, else while it arrives."""
    too_large = HTTPException(413, f"The file is larger than {limit // (1024 * 1024)} MB.")
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise too_large
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise too_large
        chunks.append(chunk)
    return b"".join(chunks)
