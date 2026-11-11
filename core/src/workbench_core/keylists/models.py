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


class EquipmentType(BaseModel):
    """A kind of equipment supplied in a package. package_id refers to an EquipmentPackage of
    the same list; types of a package are ordered as they appear in the list."""
    id: str = Field(default_factory=new_id)
    package_id: str
    name: str
    description: str = ""
    #: Predefined rows per deliverable list, exactly as a load type has them (list key -> rows,
    #: each {column name: text with <<tags>>}). The Instrument generator adds them to the
    #: Project Master lists for every Instrument Runsheet row of this type (keylists.master).
    rows: dict[str, list[dict[str, str]]] = Field(default_factory=dict)


class EquipmentPackageList(BaseModel):
    items: list[EquipmentPackage] = Field(default_factory=list)
    types: list[EquipmentType] = Field(default_factory=list)
    updated_at: datetime | None = None


RatingUnit = Literal["kW", "Amps"]
RATING_UNITS: list[str] = ["kW", "Amps"]
Phases = Literal["AC-3-phase", "AC-3-phase+N", "AC-1-phase-LN", "AC-1-phase-LL", "DC", "DC-mA"]
PHASES: list[str] = ["AC-3-phase", "AC-3-phase+N", "AC-1-phase-LN", "AC-1-phase-LL", "DC", "DC-mA"]


class AttachedFile(BaseModel):
    """A file attached to a row. The engine keeps the file itself in the project folder and
    fills this in; it is never taken from a client's save."""
    file_name: str
    size: int
    pages: int
    uploaded_at: datetime


class LoadType(BaseModel):
    """A row of the Load Types list. from_value/to_value are a range of the rating (kW or
    amps), kept as normalised decimal text so they stay exact."""
    id: str = Field(default_factory=new_id)
    code: str
    name: str
    rating_unit: RatingUnit
    voltage: int
    phases: Phases
    from_value: str | None = None
    to_value: str | None = None
    std_drg: str = ""
    bucket_type: str = ""
    load_type: str = ""
    field_options: str = ""
    multi_load: bool = False
    load_qty: int | None = None
    pdf: AttachedFile | None = None
    #: Predefined rows per deliverable list (keylists.loadgen.TEMPLATE_LISTS): list key ->
    #: rows, each {column name: text with <<tags>>}. Every load of this type produces them.
    rows: dict[str, list[dict[str, str]]] = Field(default_factory=dict)


class LoadTypeList(BaseModel):
    items: list[LoadType] = Field(default_factory=list)
    updated_at: datetime | None = None


Discipline = Literal["E", "I", "M", "P", "C", "S", "H"]
#: Discipline code -> name, in the order they are shown and kept.
DISCIPLINES: dict[str, str] = {"E": "Electrical", "I": "Instrumentation", "M": "Mechanical", "P": "Piping",
                               "C": "Civil", "S": "Structural", "H": "HVAC"}


class EquipmentCode(BaseModel):
    id: str = Field(default_factory=new_id)
    code: str
    name: str
    description: str = ""
    disciplines: list[Discipline] = Field(default_factory=list)


class EquipmentCodeList(BaseModel):
    items: list[EquipmentCode] = Field(default_factory=list)
    updated_at: datetime | None = None


class InstrumentCode(BaseModel):
    id: str = Field(default_factory=new_id)
    code: str
    name: str
    description: str = ""
    plc_code: str = ""


class InstrumentCodeList(BaseModel):
    items: list[InstrumentCode] = Field(default_factory=list)
    updated_at: datetime | None = None


class EelItem(BaseModel):
    """An item of the Electrical Equipment List. References are ids in the other key lists;
    `supplied_from` is PRIMARY_SUPPLY or a Load List row ref (see keylists.loadlist)."""
    id: str = Field(default_factory=new_id)
    tag: str
    description: str
    equipment_code_id: str
    plant_area_id: str
    vendor_package_id: str | None = None
    load_type_id: str | None = None
    rating: str | None = None  # normalised decimal text
    rating_unit: RatingUnit | None = None
    voltage: int | None = None
    phases: Phases | None = None
    is_panel: bool = False
    supplied_from: str | None = None
    manufacturer: str = ""
    model_number: str = ""
    supplied_by_id: str | None = None
    installed_by_id: str | None = None
    terminated_by_id: str | None = None


class EelList(BaseModel):
    items: list[EelItem] = Field(default_factory=list)
    updated_at: datetime | None = None
