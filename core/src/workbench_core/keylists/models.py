# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from ..refdata.models import new_id

AreaType = Literal["WBS", "Area", "Building", "Room", "Panel"]
AREA_TYPES: list[str] = ["WBS", "Area", "Building", "Room", "Panel"]


class PlantArea(BaseModel):
    """An item of the Plant Areas tree. parent_id refers to another item (None = top level);
    siblings are ordered as they appear in the list."""
    id: str = Field(default_factory=new_id)
    parent_id: str | None = None
    wbs: str = ""
    tag: str
    description: str
    area_type: AreaType


class PlantAreaList(BaseModel):
    nodes: list[PlantArea] = Field(default_factory=list)
    updated_at: datetime | None = None
