# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
from __future__ import annotations

import os
import platform
import sys
from datetime import datetime, timezone

from pydantic import BaseModel


class Greeting(BaseModel):
    message: str
    at: datetime


class EngineInfo(BaseModel):
    core_version: str
    python: str
    platform: str
    pid: int
    compiled: bool


def greet(name: str) -> Greeting:
    name = name.strip() or "world"
    return Greeting(
        message=f"Hello, {name}! This came from the Python engine.",
        at=datetime.now(timezone.utc),
    )


def engine_info() -> EngineInfo:
    from . import __version__

    return EngineInfo(
        core_version=__version__,
        python=sys.version.split()[0],
        platform=f"{platform.system()} {platform.release()} ({platform.machine()})",
        pid=os.getpid(),
        # Nuitka sets __compiled__ in every compiled module.
        compiled="__compiled__" in globals(),
    )
