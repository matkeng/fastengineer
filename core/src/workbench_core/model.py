# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""A tiny slice of the shared document model (spec section 7).

Every object has a stable UUID; engineering properties live on the object,
geometry lives per view. Here we only model one piece of equipment.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class Equipment(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    tag: str
    description: str = ""
    rating_kw: float | None = None
    views: list[str] = Field(
        default_factory=list,
        description="Views this object appears in (schematic, 2d, 3d, table)",
    )


def demo_equipment() -> list[Equipment]:
    return [
        Equipment(tag="P-101", description="Feed pump", rating_kw=30.0,
                  views=["schematic", "2d", "3d", "table"]),
        Equipment(tag="M-204", description="Agitator motor", rating_kw=7.5,
                  views=["schematic", "table"]),
        Equipment(tag="CB-0412", description="Motor circuit breaker",
                  views=["schematic"]),
    ]
