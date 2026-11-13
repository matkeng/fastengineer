# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Instrument Types: what an instrument loop on the P&IDs is (Level Transmitter, Density
Transmitter, 2 x Conveyor Drift Switch…), each with the P&ID function codes its tags have
(a density transmitter: DE, DX, DIT for the element, the source and the transmitter).

The PID Symbols list's Loops view groups the detections by loop number and gives each loop an
instrument type: the one whose functions best match the loop's (`suggest_type`), until a person
chooses one.
"""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import BaseModel, Field

from ..refdata.models import RefValidationError, new_id
from ..refdata.validate import name_key

#: (name, function codes) a project starts with: common ISA types; edit them to suit.
DEFAULT_TYPES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Level Transmitter", ("LE", "LT", "LIT")),
    ("Density Transmitter", ("DE", "DX", "DIT")),
    ("Flow Transmitter", ("FE", "FT", "FIT")),
    ("Pressure Transmitter", ("PT", "PIT")),
    ("Temperature Transmitter", ("TE", "TT", "TIT")),
    ("Pressure Gauge", ("PI",)),
    ("Temperature Gauge", ("TI",)),
    ("Level Switch", ("LS", "LSH", "LSL")),
    ("Pressure Switch", ("PS", "PSH", "PSL")),
    ("Flow Control Valve", ("FV", "FY", "FCV")),
    ("Level Control Valve", ("LV", "LY", "LCV")),
    ("Pressure Control Valve", ("PV", "PY", "PCV")),
    ("Pressure Safety Valve", ("PSV",)),
    ("2 x Conveyor Drift Switch", ("ZS",)),
)
_CODE = re.compile(r"^[A-Z][A-Z0-9]{0,9}$")


class InstrumentType(BaseModel):
    id: str = Field(default_factory=new_id)
    name: str
    functions: list[str] = Field(default_factory=list)  # P&ID function codes: DE, DX, DIT
    description: str = ""


class InstrumentTypeList(BaseModel):
    items: list[InstrumentType] = Field(default_factory=list)
    updated_at: datetime | None = None


def default_instrument_types() -> list[InstrumentType]:
    """The types a project starts with (ids are stable: "it-<name>")."""
    return [InstrumentType(id="it-" + re.sub(r"[^a-z0-9]+", "-", n.casefold()).strip("-"), name=n, functions=list(f))
            for n, f in DEFAULT_TYPES]


def parse_functions(value: object) -> list[str]:
    """Function codes as typed: "DE, DX DIT" or a list -> ["DE", "DX", "DIT"] (upper case, once each, in order)."""
    parts = value if isinstance(value, list) else re.split(r"[\s,;/]+", str(value or ""))
    out: list[str] = []
    for p in parts:
        code = str(p).strip().upper()
        if code and code not in out:
            out.append(code)
    return out


def check_instrument_types(rows: list[dict]) -> list[InstrumentType]:
    """Check the rows as sent: a name, unique (ignoring case and extra spaces); function codes
    of letters and digits starting with a letter (up to 10), each in one type only. Order is kept."""
    errors: dict[str, str] = {}
    out: list[InstrumentType] = []
    ids: set[str] = set()
    names: set[str] = set()
    owner: dict[str, str] = {}
    for raw in rows:
        rid = str(raw.get("id") or new_id())
        if rid in ids:
            raise RefValidationError("Two instrument types have the same id.", {f"{rid}.name": "Duplicate item"})
        ids.add(rid)
        name = " ".join(str(raw.get("name") or "").split())
        if not name:
            errors[f"{rid}.name"] = "A name is required"
        elif name_key(name) in names:
            errors[f"{rid}.name"] = f"'{name}' is in the list twice"
        names.add(name_key(name))
        functions = parse_functions(raw.get("functions"))
        bad = [f for f in functions if not _CODE.match(f)]
        if bad:
            errors[f"{rid}.functions"] = f"Not a function code: {', '.join(bad)} (letters and digits, starting with a letter)"
        twice = [f for f in functions if f in owner]
        if twice and f"{rid}.functions" not in errors:
            errors[f"{rid}.functions"] = "; ".join(f"{f} is already a function of {owner[f]}" for f in twice)
        for f in functions:
            owner.setdefault(f, name)
        out.append(InstrumentType(id=rid, name=name, functions=functions, description=" ".join(str(raw.get("description") or "").split())))
    if errors:
        raise RefValidationError(f"{len(errors)} problem(s) in the instrument types.", errors)
    return out


def suggest_type(functions: list[str], types: list[InstrumentType]) -> InstrumentType | None:
    """The type a loop with these function codes most likely is: the one sharing the most codes
    with it (on a tie, the one with fewest codes the loop doesn't have, then the list's order).
    None when no type shares a code."""
    have = {f.upper() for f in functions}
    best: tuple[int, int, int] | None = None
    pick = None
    for i, t in enumerate(types):
        codes = set(t.functions)
        shared = len(codes & have)
        if not shared:
            continue
        score = (shared, -len(codes - have), -i)
        if best is None or score > best:
            best, pick = score, t
    return pick


__all__ = ["InstrumentType", "InstrumentTypeList", "DEFAULT_TYPES", "default_instrument_types", "parse_functions",
           "check_instrument_types", "suggest_type"]
