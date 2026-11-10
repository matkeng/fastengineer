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


PackageType = Literal["Vendor", "Client", "SWR Supplier", "Valves", "Instrumentation", "Large Mech", "Installer", "Other"]
PACKAGE_TYPES: list[str] = ["Vendor", "Client", "SWR Supplier", "Valves", "Instrumentation", "Large Mech", "Installer",
                            "Other"]


class EquipmentPackage(BaseModel):
    """A row of the Equipment Packages list; rows are ordered as they appear in the list."""
    id: str = Field(default_factory=new_id)
    number: str
    description: str
    vendor: str = ""
    package_type: PackageType


class EquipmentPackageList(BaseModel):
    items: list[EquipmentPackage] = Field(default_factory=list)
    updated_at: datetime | None = None
