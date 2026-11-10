# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Key lists: the built-in lists every project has, with fixed columns and rules.

Plant Areas is a tree (WBS, area, building, room, panel) whose items have a WBS
number, a tag number, a description and an area type.
Equipment Packages is a flat list of package number, description, vendor name
and package type; each package has equipment types under it.
"""

from .models import (
    AREA_TYPES,
    PACKAGE_TYPES,
    AreaType,
    EquipmentPackage,
    EquipmentPackageList,
    EquipmentType,
    PackageType,
    PlantArea,
    PlantAreaList,
)
from .validate import check_equipment_packages, check_plant_areas, plant_area_depth

__all__ = [
    "AREA_TYPES", "PACKAGE_TYPES", "AreaType", "EquipmentPackage", "EquipmentPackageList", "EquipmentType", "PackageType",
    "PlantArea", "PlantAreaList", "check_equipment_packages", "check_plant_areas", "plant_area_depth",
]
