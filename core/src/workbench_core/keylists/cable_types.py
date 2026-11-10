# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Cable Types: a flat key list every project starts with a default set of.

The defaults are written as runs of sizes that share everything else; `sort` is the row's
place in the original list (gaps are where that list had blank spacer rows)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from ..refdata.models import ColumnDef, RefValidationError, new_id
from ..refdata.validate import coerce, name_key

_INTEGER = ColumnDef(name="", type="integer")
TEXT_FIELDS = ("code", "application", "type", "cores", "diameter", "voltage", "description")


class CableType(BaseModel):
    id: str = Field(default_factory=new_id)
    code: str
    application: str = ""  # e.g. AC_415V, DC_24V, Earth, Network
    type: str = ""  # e.g. Power, Control, Instrument, VSD
    cores: str = ""  # e.g. 3C+E, 4PR
    diameter: str = ""  # conductor size (text: "2.5", but also "SM", "Indoor")
    voltage: str = ""  # voltage grade, e.g. 0.6/1kV
    description: str = ""
    sort: int | None = None


class CableTypeList(BaseModel):
    items: list[CableType] = Field(default_factory=list)
    updated_at: datetime | None = None


def check_cable_types(rows: list[dict]) -> list[CableType]:
    """Check the rows as sent: the code is required and unique (ignoring case and extra
    spaces), text is trimmed, and sort is a whole number or blank. Order is kept."""
    errors: dict[str, str] = {}
    out: list[CableType] = []
    ids: set[str] = set()
    codes: set[str] = set()
    for raw in rows:
        rid = str(raw.get("id") or new_id())
        if rid in ids:
            raise RefValidationError("Two cable types have the same id.", {f"{rid}.code": "Duplicate item"})
        ids.add(rid)
        data = {f: str(raw.get(f) if raw.get(f) is not None else "").strip() for f in TEXT_FIELDS}
        if not data["code"]:
            errors[f"{rid}.code"] = "Code is required"
        elif name_key(data["code"]) in codes:
            errors[f"{rid}.code"] = f"Code '{data['code']}' is used twice"
        codes.add(name_key(data["code"]))
        sort = None
        try:
            sort = coerce(raw.get("sort"), _INTEGER, None)
        except ValueError as exc:
            errors[f"{rid}.sort"] = str(exc)
        out.append(CableType(id=rid, sort=sort, **data))
    if errors:
        raise RefValidationError(f"{len(errors)} problem(s) in the cable types.", errors)
    return out


# -- the default list ------------------------------------------------------------------------

_KV = "0.6/1kV"
_INST = "110Vac/150Vdc"
_V90 = "Cu-PVC-PVC-V90 (Power)"
_X90 = "Cu-XLPE-PVC-X90 (Power)"
_FLEX = "Flex-Cu-XLPE-TPE-90C (Flex Power)"
_PILOT = "Flex + Pilot-Cu-XLPE-TPE-90C (Flex + Pilot Power)"
_PAIRS = "Cu-V90RPPVC-OvScn-V90RPPVC (Instrolex Pairs)"
_PAIRS_IN = "Cu-V90RPPVC-InOvScn-V90RPPVC (Instrolex Pairs)"
_SMALL = ["1.5", "2.5", "4", "6", "10", "16"]
_LARGE = ["25", "35", "50", "70", "95", "120", "150", "185", "240", "300"]
_PR = ["1PR", "2PR", "4PR", "6PR", "8PR", "10PR", "12PR", "16PR", "20PR", "24PR", "36PR", "50PR"]
_FIBRE = "Loose Tube - SM, FRP/GRP Armoured Nylon Jacket"

#: (first sort, application, type, voltage, description, [(cores, diameter), ...])
_RUNS: list[tuple[int, str, str, str, str, list[tuple[str, str]]]] = [
    (1, "AC_240V", "Power", _KV, _V90, [("2C+E", s) for s in _SMALL]),
    (7, "AC_240V", "Power", _KV, _X90, [("2C+E", s) for s in _LARGE[:7]]),
    (15, "AC_415V", "Power", _KV, _V90, [("3C+E", s) for s in _SMALL]),
    (21, "AC_415V", "Power", _KV, _X90, [("3C+E", s) for s in _LARGE]),
    (32, "AC_415V", "Power", _KV, _V90, [("4C+E", s) for s in _SMALL[:4]]),
    (37, "AC_415V", "Power", _KV, _V90, [("6C+E", "4")]),
    (39, "AC_415V", "Power", _KV, _V90, [("4C+E", "10"), ("4C+E", "16")]),
    (41, "AC_415V", "Power", _KV, _X90, [("4C+E", s) for s in _LARGE]),
    (52, "DC_24V", "Control", _KV, "Cu-PVC-PVC-V90 (Control)",
     [(f"{n}+E", "1.5") for n in (2, 5, 6, 8, 10, 12, 20, 30, 36, 50)]),
    (63, "DC_24V", "Control", _INST, _PAIRS, [(c, "1.5") for c in _PR]),
    (76, "DC_24V", "Instrument", _INST, _PAIRS, [("1PR", "1.5")]),
    (77, "DC_24V", "Instrument", _INST, _PAIRS_IN, [(c, "1.5") for c in _PR[1:]]),
    (89, "DC_24V", "Instrument", _INST, "Cu-V90RPPVC-OvScn-V90RPPVC (Instrolex Triples)", [("1TR", "1.5")]),
    (90, "DC_24V", "Instrument", _INST, "Cu-V90RPPVC-InOvScn-V90RPPVC (Instrolex Triples)", [("6TR", "1.5"), ("12TR", "1.5")]),
    (93, "AC_240V", "Power Flex", _KV, _FLEX, [("2C+E", s) for s in ("1.5", "2.5", "4", "25", "6", "95")]),
    (100, "AC_415V", "Power Pilot", _KV, _PILOT, [("3C+E+Pilot", s) for s in _SMALL + _LARGE]),
    (117, "AC_415V", "Power Flex", _KV, _FLEX, [("3C+E", s) for s in _SMALL + _LARGE]),
    (134, "AC_415V", "Power Flex", _KV, _FLEX, [("4C+E", s) for s in _SMALL + _LARGE]),
    (151, "AC_415V", "Power Flex", _KV, _FLEX, [("1C", s) for s in ["10", "16"] + _LARGE + ["400"]]),
    (164, "AC_415V", "Power Flex", _KV, "Flex-Cu-XLPE-TPE-X110 (Flex Power)", [("1C", "500")]),
    (165, "AC_415V", "Power Flex", _KV, _FLEX, [("1C", "630")]),
    (167, "AC_415V", "VSD", _KV, "Cu-XLPE-PVC-X90 (Power VSD)", [("3C+3E", s) for s in _SMALL[1:] + _LARGE]),
    (183, "AC_415V", "VSD Flex", _KV, "Flex-Cu-XLPE-PVC-TaScn-PVC-90C (Varolex Flexible VSD)",
     [("3C+3E", s) for s in _SMALL[1:] + _LARGE]),
    (199, "AC_415V", "Power", _KV, _X90, [("1C", s) for s in ["16"] + _LARGE + ["400", "500", "630"]]),
    (214, "Earth", "PVC", _KV, "Cu-PVC-X90 (Earth)",
     [("1C", s) for s in ("6", "10", "16", "25", "35", "150", "185", "240", "300", "400", "500", "630", "70", "120")]),
    (229, "Earth", "BARE", _KV, "Cu-Bare-Earth", [("Bare", "120")]),
    (231, "Network", "Fibre", "N/A", _FIBRE, [("24C", "SM"), ("12C", "SM"), ("6C", "SM")]),
    (234, "Network", "Fibre", "N/A", "Loose Tube - SM, LSZH Jacket", [("2C", "SM")]),
    (237, "Network", "Ethernet", "N/A", "Cu-PVC-F/UTP - CAT6A", [("CAT6A", "Indoor")]),
    (238, "Network", "Ethernet", "N/A", "Cu-HDPE-SF/UTP CAT6 Outdoor", [("CAT6A", "Outdoor")]),
]


def default_cable_types() -> list[CableType]:
    """The cable types a project starts with (ids are stable: "d<sort>")."""
    out = [CableType(id="d14", code="Vendor - Vendor - VENDOR - VENDOR", application="VENDOR", type="VENDOR", cores="VENDOR",
                     diameter="VENDOR", voltage="VENDOR", description="VENDOR", sort=14)]
    for first, application, kind, voltage, description, sizes in _RUNS:
        for i, (cores, diameter) in enumerate(sizes):
            out.append(CableType(id=f"d{first + i}", code=f"{application} - {kind} - {cores} - {diameter}",
                                 application=application, type=kind, cores=cores, diameter=diameter, voltage=voltage,
                                 description=description, sort=first + i))
    return sorted(out, key=lambda c: c.sort or 0)
