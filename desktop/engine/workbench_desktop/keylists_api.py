# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Key lists: the built-in lists of a project: Plant Areas (a tree) and Equipment Packages."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from workbench_core.keylists import (
    AREA_TYPES,
    PACKAGE_TYPES,
    EquipmentPackage,
    EquipmentPackageList,
    PlantArea,
    PlantAreaList,
    check_equipment_packages,
    check_plant_areas,
    plant_area_depth,
)
from workbench_core.refdata import RefValidationError

from .refdata_api import invalid
from .storage import get_keylists

router = APIRouter(prefix="/api/keylists", tags=["key lists"])


@router.get("")
def overview() -> dict:
    lists = get_keylists()
    areas = lists.plant_areas()
    return {"plant_areas": {"items": len(areas.nodes), "depth": plant_area_depth(areas)}, "area_types": AREA_TYPES,
            "equipment_packages": {"items": len(lists.equipment_packages().items)}, "package_types": PACKAGE_TYPES}


@router.get("/plant-areas", response_model=PlantAreaList)
def get_plant_areas() -> PlantAreaList:
    return get_keylists().plant_areas()


class PlantAreasUpdate(BaseModel):
    nodes: list[PlantArea]


@router.put("/plant-areas", response_model=PlantAreaList)
def update_plant_areas(body: PlantAreasUpdate):
    try:
        return get_keylists().save_plant_areas(check_plant_areas(PlantAreaList(nodes=body.nodes)))
    except RefValidationError as exc:
        return invalid(exc)


@router.get("/equipment-packages", response_model=EquipmentPackageList)
def get_equipment_packages() -> EquipmentPackageList:
    return get_keylists().equipment_packages()


class EquipmentPackagesUpdate(BaseModel):
    items: list[EquipmentPackage]


@router.put("/equipment-packages", response_model=EquipmentPackageList)
def update_equipment_packages(body: EquipmentPackagesUpdate):
    try:
        return get_keylists().save_equipment_packages(
            check_equipment_packages(EquipmentPackageList(items=body.items)))
    except RefValidationError as exc:
        return invalid(exc)
