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


class ComponentRow(BaseModel):
    """A row of a component table: the range of the matched field it is for (blank: open-ended,
    kept as normalised decimal text), and its values by column name."""
    min: str | None = None
    max: str | None = None
    values: dict[str, str] = Field(default_factory=dict)


class ComponentTable(BaseModel):
    """A load type's table of components (circuit breaker, contactor… part numbers) that depend
    on a load's value: a load gets the first row whose Min <= its `match_field` <= Max, and a
    template row reaches it as <<LoadType.<name>.<column>>> (keylists.tag_paths)."""
    id: str = Field(default_factory=new_id)
    name: str  # what tags call it: CB in <<LoadType.CB.PartNumber>>
    match_field: str = "load_rating"  # a Load List field's key (calculated ones too) or a load tag (rating, voltage…)
    columns: list[str] = Field(default_factory=lambda: ["Part Number", "Manufacturer", "Description"])
    rows: list[ComponentRow] = Field(default_factory=list)


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
    #: The Starter Coordination chart its loads' starters come from (keylists.starters): blank
    #: is the project's default chart, "None" no starter.
    starter_chart: str = ""
    pdf: AttachedFile | None = None
    #: Predefined rows per deliverable list (keylists.loadgen.TEMPLATE_LISTS): list key ->
    #: rows, each {column name: text with <<tags>>}. Every load of this type produces them.
    rows: dict[str, list[dict[str, str]]] = Field(default_factory=dict)
    #: Component tables (circuit breakers, contactors…): a part per range of a load's rating
    #: or another of its fields, reached from template rows as <<LoadType.CB.PartNumber>>.
    components: list[ComponentTable] = Field(default_factory=list)


class LoadTypeList(BaseModel):
    items: list[LoadType] = Field(default_factory=list)
    updated_at: datetime | None = None


#: The disciplines a project starts with: code -> name, in the order they are shown and kept.
#: A project can change them (its Disciplines enum, see keylists.enums); codes are what is stored.
DISCIPLINES: dict[str, str] = {"E": "Electrical", "I": "Instrumentation", "M": "Mechanical", "P": "Piping",
                               "C": "Civil", "S": "Structural", "H": "HVAC", "PR": "Process", "G": "General"}


class EquipmentCode(BaseModel):
    id: str = Field(default_factory=new_id)
    code: str
    name: str
    description: str = ""
    disciplines: list[str] = Field(default_factory=list)  # codes of the project's Disciplines enum


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
