# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Key lists: the built-in lists every project has, with fixed columns and rules.

Plant Areas is a tree (WBS, area, building, room, panel) whose items have a WBS
number, a tag number, a description and an area type.
"""

from .models import AREA_TYPES, AreaType, PlantArea, PlantAreaList
from .validate import check_plant_areas, plant_area_depth

__all__ = ["AREA_TYPES", "AreaType", "PlantArea", "PlantAreaList", "check_plant_areas", "plant_area_depth"]
