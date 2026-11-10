# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Key lists: the built-in lists every project has, with fixed columns and rules.

Plant Areas is a tree (WBS, area, building, room, panel) whose items have a WBS
number, a tag number, a description and an area type.
Equipment Packages is a flat list of package number, description, vendor name
and package type; each package has equipment types under it.
Load Types is a flat list of electrical load definitions. Equipment Codes and
Instrument Codes are flat lists of codes (with disciplines / a PLC code).
The Load List combines the MEL and EEL imports, with a plant area and a load type
allocated to each row.
"""

from .models import (
    AREA_TYPES,
    DISCIPLINES,
    AttachedFile,
    EquipmentCode,
    EquipmentCodeList,
    InstrumentCode,
    InstrumentCodeList,
    PACKAGE_TYPES,
    PHASES,
    RATING_UNITS,
    AreaType,
    EquipmentPackage,
    EquipmentPackageList,
    EquipmentType,
    LoadType,
    LoadTypeList,
    PackageType,
    PlantArea,
    PlantAreaList,
)
from .loadlist import (
    LOAD_LIST_TARGETS,
    PRIMARY_SUPPLY,
    LoadListRow,
    apply_auto,
    apply_auto_supply,
    auto_match,
    match_index,
    panel_index,
    supply_loop,
)
from .validate import check_code_list, check_equipment_packages, check_load_types, check_plant_areas, plant_area_depth

__all__ = [
    "DISCIPLINES", "EquipmentCode", "EquipmentCodeList", "InstrumentCode", "InstrumentCodeList", "check_code_list",
    "LOAD_LIST_TARGETS", "PRIMARY_SUPPLY", "LoadListRow", "apply_auto", "apply_auto_supply", "auto_match", "match_index",
    "panel_index", "supply_loop",
    "AREA_TYPES", "AttachedFile", "PACKAGE_TYPES", "AreaType", "EquipmentPackage", "EquipmentPackageList", "EquipmentType", "PackageType",
    "PlantArea", "PlantAreaList", "LoadType", "LoadTypeList", "PHASES", "RATING_UNITS", "check_load_types",
    "check_equipment_packages", "check_plant_areas", "plant_area_depth",
]
