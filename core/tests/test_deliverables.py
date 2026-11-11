# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
import pytest

from workbench_core.deliverables import Deliverable, apply_filter, check_deliverable, content_rows, next_letter
from workbench_core.generators.models import BuildResult, BuildStats, OutputRow
from workbench_core.refdata import RefValidationError


def test_letters() -> None:
    assert next_letter([]) == "A" and next_letter(["A"]) == "B" and next_letter(["B", "A"]) == "C"
    assert next_letter([chr(65 + i) for i in range(26)]) == "AA" and next_letter(["AA"]) == "AB"
    assert next_letter(["AZ"]) == "BA" and next_letter(["ZZ"]) == "AAA"


def _result() -> BuildResult:
    rows = [OutputRow(cells=["T", "C-1", "100"], run_row_id="1"), OutputRow(cells=[None, None, None]),
            OutputRow(cells=["T", "C-2", " 200 "], run_row_id="2"), OutputRow(cells=["T", "C-3", 300], run_row_id="3")]
    return BuildResult(header=["TEMPLATE", "Cable Number", "Area"], rows=rows, stats=BuildStats())


def test_filter() -> None:
    r = _result()
    assert apply_filter(r, "", []) is r and content_rows(r) == 3
    kept = apply_filter(r, " area ", ["200", "300"])
    assert [x.cells[1] for x in kept.rows] == ["C-2", "C-3"]  # as text; separators dropped
    assert apply_filter(r, "Area", ["999"]).rows == []
    with pytest.raises(RefValidationError):
        apply_filter(r, "Zone", ["1"])


def test_check() -> None:
    a = Deliverable(id="a", type="Cable Schedule", name="Lighting", generator_id="g1")
    ok = check_deliverable(Deliverable(type="Load List", name=" Loads ", generator_id="g1", filter_column=" Area ",
                                       filter_values=["100", " 100 ", ""]), [a], {"g1"}, ["Cable Number", "Area"])
    assert (ok.name, ok.filter_column, ok.filter_values) == ("Loads", "Area", ["100"])
    with pytest.raises(RefValidationError) as e:
        check_deliverable(Deliverable(type="Load List", name="lighting ", generator_id="zz", filter_column="Zone"),
                          [a], {"g1"}, ["Area"])
    assert set(e.value.fields) == {"name", "generator_id", "filter_column", "filter_values"}
