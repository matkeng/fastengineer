# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""The project's Load List fields (mel.load_fields)."""

from __future__ import annotations

import pytest

from workbench_core.mel.load_fields import FieldEdit, LoadField, LoadFields, default_load_fields, new_key, plan_change
from workbench_core.mel.models import ELEC_LOAD_FIELDS, FieldMap, Recipe, fields_for
from workbench_core.mel.pipeline import PipelineResult, output_list
from workbench_core.refdata import RefValidationError


def _same() -> list[FieldEdit]:
    return [FieldEdit(key=f.key, label=f.label, kind=f.kind) for f in default_load_fields().fields]


def test_defaults_and_new_keys() -> None:
    d = default_load_fields()
    assert d.keys() == ELEC_LOAD_FIELDS and d.labels()["load_units"] == "Load units (kW, HP…)"
    assert {"load_rating", "phases"} <= d.numeric() and d.boolean() == {"is_a_loadcentre", "is_deleted"}
    assert new_key("Weight (kg)", set()) == "weight_kg" and new_key("Weight (kg)", {"weight_kg"}) == "weight_kg_2"
    assert new_key("Plant area", set()) == "plant_area_2"  # <<PlantArea>> is the app's own tag
    assert new_key("3 phase", set()) == "f_3_phase" and new_key("!!", set()) == "field"


def test_plan_change() -> None:
    edits = _same()
    edits[2] = FieldEdit(key="tag", label="Equipment tag")
    edits = [e for e in edits if e.key != "status"] + [FieldEdit(label="Motor HP", kind="number")]
    ch = plan_change(default_load_fields(), edits)
    assert ch.relabelled == {"tag": ("Tag", "Equipment tag")} and ch.deletes == ["status"] and ch.added == ["motor_hp"]
    assert ch.fields.labels()["tag"] == "Equipment tag" and ch.fields.numeric() >= {"motor_hp"}
    assert plan_change(default_load_fields(), _same()).deletes == []


@pytest.mark.parametrize("edit, message", [
    (lambda e: [x for x in e if x.key != "load_type"], "not deleted"),
    (lambda e: [x.model_copy(update={"kind": "number"}) if x.key == "area" else x for x in e], "keeps its kind"),
    (lambda e: [*e, FieldEdit(label="TAG")], "twice"),
    (lambda e: [*e, FieldEdit(key="area", label="Area 2")], "twice"),
    (lambda e: [*e, FieldEdit(label="")], "needs a name"),
])
def test_what_is_refused(edit, message) -> None:
    with pytest.raises(RefValidationError) as exc:
        plan_change(default_load_fields(), edit(_same()))
    assert message in " ".join(exc.value.fields.values())


def test_imports_map_onto_the_project_fields() -> None:
    lf = LoadFields(fields=[LoadField(key="tag", label="Tag"), LoadField(key="motor_hp", label="Motor HP", kind="number"),
                            LoadField(key="spare", label="Spare", kind="yes/no")])
    assert fields_for("MEL", lf.keys()) == ["tag", "motor_hp", "spare"] and fields_for("PIL", lf.keys())[0] == "tag"
    assert fields_for("EEL") == ELEC_LOAD_FIELDS
    recipe = Recipe(id="r", name="r", target="MEL", mapping=[FieldMap(field="motor_hp", column="HP"), FieldMap(field="spare", column="S"),
                                                     FieldMap(field="desc", column="D")])
    result = PipelineResult.model_validate({"stage": "auto", "headers": ["HP", "S", "D"], "source_headers": ["HP", "S", "D"], "key_header": "HP",
                                            "rows": [{"key": "1", "origin": "file", "file_row": 1, "values": {"HP": "40", "S": "yes", "D": "Pump"}}]})
    out = output_list(result, recipe, lf)
    assert out.fields == ["motor_hp", "spare"] and out.rows == [{"motor_hp": 40, "spare": True}]  # desc isn't a field here
    assert output_list(result, recipe).fields == ["desc"]  # the built-in fields
