# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""The fields of the Project Master Load List, which a project can edit.

The Load List's fields are what an import (MEL, ELL, EEL, LIL) maps its columns onto, and
what the Load List shows. A project starts with the built-in ones (models.ELEC_LOAD_FIELDS)
and can relabel, add, delete and reorder them.

Each field has a **key** that never changes (it is what imports' mappings, the rows' values
and the <<tags>> of load types' rows use) and a **label** that is what people see. Renaming
a field changes its label only, so nothing that uses it has to change. A new field's key is
made from its label when it is added.

Fields the app itself reads (`LOCKED`: the tag, description, area, load type, rating…) can be
relabelled and moved, not deleted, and keep their kind.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from ..refdata.models import RefValidationError
from .models import ELEC_LOAD_FIELDS, NUMERIC_FIELDS

Kind = Literal["text", "number", "yes/no", "calc"]
BOOLEAN_FIELDS = {"is_a_loadcentre", "is_deleted"}

#: What each built-in field is called until a project relabels it.
DEFAULT_LABELS: dict[str, str] = {
    "area": "Area", "sub_area": "Sub-area", "tag": "Tag", "equip_qty": "Quantity", "standby_qty": "Standby quantity",
    "multi_load": "Multiple loads", "desc": "Description", "equip_type": "Equipment type", "equip_subtype": "Equipment subtype",
    "load_units": "Load units (kW, HP…)", "load_rating": "Load rating", "load_voltage": "Voltage", "csv_row_num": "Source row number",
    "phases": "Phases", "status": "Status", "starter_type": "Starter type", "load_type": "Load type", "starter_addons": "Starter add-ons",
    "load_addons": "Load add-ons", "field_addons": "Field add-ons", "is_a_loadcentre": "Is a load centre", "loadcentre": "Load centre",
    "supplied_from": "Supplied from", "is_deleted": "Deleted",
}
#: Fields the app reads (allocations, the deliverable, distribution panels, the Electrical
#: Equipment List): they can be relabelled and moved, not deleted, and keep their kind.
LOCKED: tuple[str, ...] = ("tag", "desc", "area", "equip_type", "equip_qty", "load_units", "load_rating", "load_voltage",
                           "phases", "load_type", "is_a_loadcentre", "supplied_from", "is_deleted")
#: Keys a new field can't have: the tags load types' rows can use that the app works out
#: itself (loadgen.tags_for), which would hide a field's own value.
_DERIVED = {"tag", "description", "area", "rating", "units", "voltage", "phases", "equiptype", "qty", "plantarea",
            "plantareadesc", "loadtype", "loadtypename", "suppliedfrom", "suppliedfromdesc", "stddrg", "buckettype", "source",
            "row", "cableno", "cabletype", "cablecode", "cablecores", "cablesize", "cableinsulation",
            # the links dot notation follows (keylists.tag_paths)
            "suppliedfrom", "eel", "cable", "parent", "equipmenttype", "package", "system",
            # what a calculation or a summary can use about a load (keylists.load_calcs.load_cells)
            "supplychain", "ispanel"}
MAX_FIELDS = 80
MAX_LABEL = 60


def _kind(key: str) -> Kind:
    return "number" if key in NUMERIC_FIELDS else "yes/no" if key in BOOLEAN_FIELDS else "text"


class CalcCheck(BaseModel):
    """A check on a calculated field's answer: `rule` is an expression that holds for a good
    answer (<<value>> is the answer, other <<fields>> of the row can be used too)."""
    rule: str
    message: str = ""  # shown when the rule doesn't hold (default: the rule)
    severity: Literal["error", "warning"] = "error"


class LoadCalc(BaseModel):
    """How a calculated field is worked out for each row of the Load List, like a spreadsheet
    formula that refers to the row's other cells as <<field>>.

    Rows where `applies_if` (blank: every row) does not hold get `otherwise` (blank: nothing);
    the others get `formula`, rounded to `decimals` when it is a number, then each of `checks`."""
    applies_if: str = ""
    formula: str = ""
    otherwise: str = ""
    decimals: int | None = Field(default=None, ge=0, le=10)
    checks: list[CalcCheck] = Field(default_factory=list)


class LoadField(BaseModel):
    key: str
    label: str
    kind: Kind = "text"
    calc: LoadCalc | None = None  # kind "calc" only


class LoadFields(BaseModel):
    """The project's Load List fields, in order."""
    fields: list[LoadField] = Field(default_factory=list)

    def keys(self) -> list[str]:
        return [f.key for f in self.fields]

    def importable(self) -> list[str]:
        """The fields an import maps onto: all but the calculated ones."""
        return [f.key for f in self.fields if f.kind != "calc"]

    def calcs(self) -> list[LoadField]:
        return [f for f in self.fields if f.kind == "calc" and f.calc is not None]

    def labels(self) -> dict[str, str]:
        return {f.key: f.label for f in self.fields}

    def numeric(self) -> set[str]:
        return {f.key for f in self.fields if f.kind == "number"}

    def boolean(self) -> set[str]:
        return {f.key for f in self.fields if f.kind == "yes/no"}


def default_load_fields() -> LoadFields:
    return LoadFields(fields=[LoadField(key=k, label=DEFAULT_LABELS.get(k, k), kind=_kind(k)) for k in ELEC_LOAD_FIELDS])


class FieldEdit(BaseModel):
    """One field as edited: its key ("" for a new field), label and kind (and calculation)."""
    key: str = ""
    label: str
    kind: Kind = "text"
    calc: LoadCalc | None = None


class FieldChange(BaseModel):
    fields: LoadFields
    relabelled: dict[str, tuple[str, str]] = Field(default_factory=dict)  # key -> (old label, new label)
    deletes: list[str] = Field(default_factory=list)  # keys
    added: list[str] = Field(default_factory=list)  # keys
    rekinded: dict[str, tuple[str, str]] = Field(default_factory=dict)  # key -> (old kind, new kind)
    recalculated: list[str] = Field(default_factory=list)  # keys of calculated fields whose calculation changed


def new_key(label: str, taken: set[str]) -> str:
    """A key for a new field, from its label: lower case, words joined by _ (weight_kg)."""
    base = re.sub(r"[^a-z0-9]+", "_", label.casefold()).strip("_")[:40] or "field"
    if base[0].isdigit():
        base = f"f_{base}"
    key, n = base, 2
    while key in taken or key.replace("_", "") in _DERIVED:
        key, n = f"{base}_{n}", n + 1
    return key


def _calc(e: FieldEdit, errors: dict[str, str], i: int) -> LoadCalc | None:
    if e.kind != "calc":
        return None
    if e.calc is None or not e.calc.formula.strip():
        errors[f"{i}.formula"] = "A calculated field needs a formula"
        return e.calc
    return e.calc.model_copy(update={"checks": [c for c in e.calc.checks if c.rule.strip()]})


def plan_change(old: LoadFields, edits: list[FieldEdit]) -> FieldChange:
    """Check edited fields against the current ones and work out what changes. Raises
    RefValidationError (fields `<position>` or `fields`) on a problem."""
    errors: dict[str, str] = {}
    before = {f.key: f for f in old.fields}
    if len(edits) > MAX_FIELDS:
        errors["fields"] = f"The Load List can have at most {MAX_FIELDS} fields"
    taken = set(before) | set(ELEC_LOAD_FIELDS)
    seen: dict[str, int] = {}
    used: set[str] = set()
    out: list[LoadField] = []
    change = FieldChange(fields=LoadFields())
    for i, e in enumerate(edits):
        label = " ".join(e.label.split())
        if not label:
            errors[str(i)] = "A field needs a name"
        elif len(label) > MAX_LABEL:
            errors[str(i)] = f"At most {MAX_LABEL} characters"
        elif label.casefold() in seen:
            errors[str(i)] = f"'{label}' is in the list twice"
        seen[label.casefold()] = i
        if e.key:
            was = before.get(e.key)
            if was is None:
                errors[str(i)] = f"'{e.key}' is not a field of the Load List"
                continue
            if e.key in used:
                errors[str(i)] = f"'{was.label}' is in the list twice"
            used.add(e.key)
            kind = e.kind
            if e.key in LOCKED and kind != was.kind:
                errors[str(i)] = f"'{was.label}' keeps its kind ({was.kind}): the app reads it"
            if label and label != was.label:
                change.relabelled[e.key] = (was.label, label)
            if kind != was.kind:
                change.rekinded[e.key] = (was.kind, kind)
            calc = _calc(e, errors, i)
            if kind == "calc" and was.kind == "calc" and calc != was.calc:
                change.recalculated.append(e.key)
            out.append(LoadField(key=e.key, label=label, kind=kind, calc=calc))
        else:
            key = new_key(label, taken)
            taken.add(key)
            change.added.append(key)
            out.append(LoadField(key=key, label=label, kind=e.kind, calc=_calc(e, errors, i)))
    change.deletes = [k for k in before if k not in used]
    locked = [before[k].label for k in change.deletes if k in LOCKED]
    if locked:
        errors["fields"] = f"These fields can be moved and renamed but not deleted: {', '.join(locked)}"
    if errors:
        raise RefValidationError(f"{len(errors)} problem(s) in the Load List fields.", errors)
    change.fields = LoadFields(fields=out)
    return change


__all__ = ["CalcCheck", "LoadCalc", "LoadField", "LoadFields", "FieldEdit", "FieldChange", "LOCKED", "DEFAULT_LABELS", "default_load_fields",
           "plan_change", "new_key"]
