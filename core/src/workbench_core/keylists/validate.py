# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Rules for the project's key lists."""

from __future__ import annotations

from ..refdata.models import RefValidationError
from ..refdata.validate import name_key
from .models import PlantArea, PlantAreaList

_UNIQUE = (("tag", "Tag number", True), ("description", "Description", True), ("wbs", "WBS number", False))


def check_plant_areas(areas: PlantAreaList) -> PlantAreaList:
    """Tag numbers and descriptions are required and unique in the whole list; WBS numbers
    are optional but unique when filled in (all ignoring case and extra spaces). Parents
    must exist and there must be no cycles. Any area type may sit under any other.
    Returns the items ordered parents-first (depth-first), keeping sibling order."""
    errors: dict[str, str] = {}
    nodes: list[PlantArea] = []
    ids: set[str] = set()
    for n in areas.nodes:
        n = n.model_copy(update={"wbs": n.wbs.strip(), "tag": n.tag.strip(), "description": n.description.strip(),
                                 "parent_id": n.parent_id or None})
        if n.id in ids:
            raise RefValidationError("Two plant areas have the same id.", {f"{n.id}.tag": "Duplicate item"})
        ids.add(n.id)
        nodes.append(n)
    by_id = {n.id: n for n in nodes}

    for field, label, required in _UNIQUE:
        seen: set[str] = set()
        for n in nodes:
            value = getattr(n, field)
            if not value:
                if required:
                    errors[f"{n.id}.{field}"] = f"{label} is required"
            elif name_key(value) in seen:
                errors[f"{n.id}.{field}"] = f"{label} '{value}' is used twice"
            else:
                seen.add(name_key(value))

    for n in nodes:
        if n.parent_id is not None and n.parent_id not in by_id:
            errors[f"{n.id}.parent"] = "Its parent is not in the list"
    # Cycles: walking up from any item must reach the top.
    for n in nodes:
        seen_ids = {n.id}
        p = n.parent_id
        while p is not None and p in by_id:
            if p in seen_ids:
                errors[f"{n.id}.parent"] = "An item can't be inside itself"
                break
            seen_ids.add(p)
            p = by_id[p].parent_id
    if errors:
        raise RefValidationError(f"{len(errors)} problem(s) in the plant areas.", errors)

    children: dict[str | None, list[PlantArea]] = {}
    for n in nodes:
        children.setdefault(n.parent_id, []).append(n)
    ordered: list[PlantArea] = []

    def walk(parent: str | None) -> None:
        for c in children.get(parent, []):
            ordered.append(c)
            walk(c.id)
    walk(None)
    return areas.model_copy(update={"nodes": ordered})


def plant_area_depth(areas: PlantAreaList) -> int:
    by_id = {n.id: n for n in areas.nodes}
    best = 0
    for n in areas.nodes:
        d, p = 1, n.parent_id
        while p is not None and p in by_id and d <= len(by_id):
            d, p = d + 1, by_id[p].parent_id
        best = max(best, d)
    return best
