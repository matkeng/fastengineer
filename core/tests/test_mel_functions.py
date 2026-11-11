# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
from datetime import datetime, timezone

import pytest

from workbench_core.mel import AutoColumn, Recipe, run_pipeline
from workbench_core.mel.functions import FUNCTION_HELP, REMOVED, SAMPLE_ROW, make_interpreter
from workbench_core.mel.models import Revision

EXAMPLES = [(group, expr, result) for group, _about, items in FUNCTION_HELP for expr, result, _what in items]


def _row_result(expr: str) -> tuple[str, bool]:
    """What a calculated column with this expression as its value writes for SAMPLE_ROW."""
    headers = list(SAMPLE_ROW)
    rev = Revision(id="r", rev=1, file_name="t.csv", source="csv", key_header="Tag", num_rows=1, num_cols=len(headers),
                   uploaded_at=datetime.now(timezone.utc), headers=headers, headers_original=headers, rows=[dict(SAMPLE_ROW)])
    col = AutoColumn(name="Out", statement="True", true_val=expr, error_val="ERROR")
    row = run_pipeline(rev, Recipe(id="x", name="m", auto_columns=[col])).rows[0]
    return row.values["Out"], "Out" in row.auto_errors


@pytest.mark.parametrize("group,expr,result", EXAMPLES, ids=[e[1] for e in EXAMPLES])
def test_every_help_example_gives_what_the_help_says(group: str, expr: str, result: str) -> None:
    got, error = _row_result(expr)
    assert (got, error) == (result, False), f"{group}: {expr}"


@pytest.mark.parametrize("group,expr,result", [e for e in EXAMPLES if e[0] == "Comparisons and logic"],
                         ids=[e[1] for e in EXAMPLES if e[0] == "Comparisons and logic"])
def test_the_conditions_work_as_conditions(group: str, expr: str, result: str) -> None:
    if result not in ("TRUE", "FALSE"):
        return
    headers = list(SAMPLE_ROW)
    rev = Revision(id="r", rev=1, file_name="t.csv", source="csv", key_header="Tag", num_rows=1, num_cols=len(headers),
                   uploaded_at=datetime.now(timezone.utc), headers=headers, headers_original=headers, rows=[dict(SAMPLE_ROW)])
    col = AutoColumn(name="Out", statement=expr, true_val="yes", false_val="no")
    assert run_pipeline(rev, Recipe(id="x", name="m", auto_columns=[col])).rows[0].values["Out"] == ("yes" if result == "TRUE" else "no")


def test_a_calculated_column_cannot_reach_outside_the_row(tmp_path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("password")
    for name in REMOVED:
        assert name not in make_interpreter().symtable
    got, error = _row_result(f"open({str(secret)!r}).read()")
    assert "password" not in got  # open is unknown: the text is taken as plain text, nothing is read
    got, error = _row_result(f"open({str(secret)!r}).read() + <<Tag>>")
    assert (got, error) == ("ERROR", True)
