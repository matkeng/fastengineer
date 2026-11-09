# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Change report, Check, workbook import/export, CLI and (when the fixtures exist) golden tests."""

import os
from pathlib import Path

import pytest

from gen_helpers import make_gen
from workbench_core.generators import build, change_report, check
from workbench_core.generators.__main__ import main
from workbench_core.generators.models import Concat, Exists, Lookup, OutputRow
from workbench_core.generators.xlsx_export import export_csv, export_name, export_xlsx
from workbench_core.generators.xlsx_import import import_workbook


def rows(*cells):
    return [OutputRow(cells=list(c), run_row_id="1") for c in cells]


def test_diff_duplicate_keys_and_reordered_columns():
    old = rows(("C1", 10, "a"), ("C1", 20, "b"), ("C2", 5, "x"))
    new = rows(("b", "C1", 10), ("b2", "C1", 21), ("y", "C3", 1))  # columns reordered
    rep = change_report(["Cable Number", "Length", "To"], old, ["To", "Cable Number", "Length"], new, "Cable Number")
    assert (rep.added, rep.removed, rep.changed) == (1, 1, 2)
    by = {e.key: e for e in rep.entries}
    assert {c.column for c in by["C1"].cells} == {"To"}  # first C1: only To changed
    assert {(c.column, c.old, c.new) for c in by["C1#2"].cells} == {("Length", 20, 21), ("To", "b", "b2")}
    assert by["C3"].kind == "added" and by["C2"].kind == "removed"


def test_diff_ignores_separators_and_int_float():
    old = rows(("C1", 10)) + [OutputRow(cells=[None, None])]
    new = rows(("C1", 10.0))
    rep = change_report(["Cable Number", "L"], old, ["Cable Number", "L"], new, "Cable Number")
    assert (rep.added, rep.removed, rep.changed) == (0, 0, 0)


def check_gen():
    tags = ["<<Key>>", "<<RUN>>", "<<MECH>>", "<<SUF>>", "<<#1>>", "<<Unused>>"]
    runs = [[1, 1, "P-1", " ", 100, None], [1, 1, "P-2", " ", None, None], [9, 3, "P-1", " ", 1, None],
            [None, None, "P-3", None, None, None]]
    g = make_gen(tags, runs, ["Run", "Tag", "Parent", "CARD TYPE", "Code", "Check"],
                 {1: [["<<RUN>>", "LS<<#1>>", "<<PARENT>>", "DI-32", "x", "@computed"],
                      ["<<RUN>>", "<<Missing>>", "<<MECH_P>>", "9999-XX", "x", "@computed"]],
                  2: [["<<RUN>>", "x", "y", "DO-16", "x", "@computed"]]},
                 parents=[("P-1", "PUMP 1"), ("P-1", "dup")], diff_key="Tag", run_column="Run",
                 computed={"Check": Exists(value="Code", table="Nope", column="A")})
    return g


def test_check_rules():
    r = check(check_gen(), cards={"DI-32", "DO-16"})
    codes = {f.code for f in r.findings}
    assert {"C4", "C6", "C8", "C9", "C10", "C11", "C12", "C13", "C16", "C17", "C19", "C20"} <= codes
    c4 = next(f for f in r.findings if f.code == "C4")
    assert c4.item == "<<Missing>>" and c4.severity == "ERROR"
    assert next(f for f in r.findings if f.code == "C9").item == "P-2"
    assert next(f for f in r.findings if f.code == "C12").item == "<<Unused>>"
    assert next(f for f in r.findings if f.code == "C16").item == "9999-XX"
    assert next(f for f in r.findings if f.code == "C20").item.startswith("1 Tag")  # <<Missing>> twice
    idx = {e.id: e for e in r.template_index}
    assert idx["1"].runs == 2 and idx["1"].rows == 2 and not idx["2"].used


def test_check_fatal_tag_problems_and_no_parents():
    g = make_gen(["<<Key>>", "<<KEY>>"], [[1, 1]], ["X"], {1: [["a"]]})
    assert [f.code for f in check(g).findings] == ["C2"]
    g = make_gen(["<<Key>>", "<<A>>"], [[1, 1]], ["X"], {1: [["<<A_P>>"]]})
    assert "C5" in {f.code for f in check(g).findings}


def test_check_late_formula_parse():
    g = make_gen(["<<Key>>", "<<Q>>"], [[1, 5]], ["L"], {1: [["F=<<Q>>*"]]}, replace_f_equals=True)
    assert "C18" in {f.code for f in check(g).findings}


# -- workbook round trip --------------------------------------------------------------------

def make_workbook(path: Path):
    """A miniature DP generator workbook with the same structure as the real ones."""
    from openpyxl import Workbook
    from openpyxl.worksheet.table import Table

    wb = Workbook()
    cfg = wb.active
    cfg.title = "Config"
    cfg.append(["Setting", "Value", "Description"])
    for k, v in [("KeyPlaceholder", "<<Key>>"), ("ReplaceFEquals", "True"), ("FreezeFormulas", "True"),
                 ("ParentSheet", "Parents"), ("RunFrom", "0"), ("RunUpTo", "100"), ("DocTitle", "Lighting Schedule"),
                 ("CopyFormats", "False")]:
        cfg.append([k, v, ""])
    cfg.add_table(Table(displayName="tblConfig", ref=f"A1:C{cfg.max_row}"))
    cfg["E1"], cfg["F1"], cfg["G1"], cfg["H1"] = "Name", "Source", "Transform", "Default"
    cfg["E2"], cfg["F2"], cfg["G2"] = "<<UPKEY>>", "<<FromTag>>", "upper"
    cfg.add_table(Table(displayName="tblPlaceholders", ref="E1:H2"))

    rs = wb.create_sheet("RunSheet")
    rs.append([None, "Std", "Run", "From", "Length", "Qty"])
    rs.append([None, "<<Key>>", "<<RUN>>", "<<FromTag>>", "<<LEN>>", "<<Qty>>"])
    rs.append([None, 11, 1, "100-LB01", 70, 5])
    rs.append([None, "nr", 2, "x", 1, 1])
    rs.append([None, 12, 3, "100-LB01", 10, 2])
    rs.add_table(Table(displayName="tblRunSheet", ref="B2:F5"))

    t = wb.create_sheet("Templates")
    t.append(["TEMPLATE", "Run Num", "Cable Number", "From", "From Location", "Length", "Cable Range", "Size",
              "Cable Code", "Code Check", "Voltage"])
    t.append([11, "<<RUN>>", "<<FromTag_S>>-P1", "<<FromTag>>", "<<FromTag_P>>", "<<LEN>>", "R230", 2.5,
              '=G2&" - "&H2', "=EXACT(VLOOKUP(I2,Codes!A:A,1),I2)", '=IF(J2<>"",VLOOKUP(I2,Kinds!B:D,3,0),"")'])
    t.append([11, "<<RUN>>", 'F="<<FromTag_S>>-P2 to P"& <<QTY>>+1', "<<UPKEY>>", "", "F=<<LEN>>*<<QTY>>", "R230", 2.5,
              '=G3&" - "&H3', "=EXACT(VLOOKUP(I3,Codes!A:A,1),I3)", '=IF(J3<>"",VLOOKUP(I3,Kinds!B:D,3,0),"")'])
    t.append([12, "<<RUN>>", "<<FromTag_S>>-P9", "<<FromTag>>", "", "<<LEN>>", "R230", 4,
              '=G4&" - "&H4', "=EXACT(VLOOKUP(I4,Codes!A:A,1),I4)", "=SUM(F4:F4)"])
    t.add_table(Table(displayName="tblTemplates", ref="A1:K4"))

    p = wb.create_sheet("Parents")
    p.append([None, "ParentEquipmentTag", "Description"])
    p.append([None, "100-LB01", "NORTH YARD LIGHTING BOARD"])
    p.add_table(Table(displayName="tblParents", ref="B1:C2"))
    lists = wb.create_sheet("Codes")
    for v in ["R230 - 1.5", "R230 - 2.5", "R230 - 4"]:
        lists.append([v])
    ct = wb.create_sheet("Kinds")
    ct.append([None, "Code", "x", "Voltage"])
    ct.append([None, "R230 - 2.5", "x", "LV"])
    o = wb.create_sheet("Output")
    o.append(["TEMPLATE", "Run Num", "Cable Number"])
    wb.save(path)


def test_import_build_export_roundtrip(tmp_path):
    src = tmp_path / "lighting_dp_generator_test.xlsx"
    make_workbook(src)
    res = import_workbook(src)
    g, rep = res.generator, res.report
    assert g.id == "dp" and g.config.replace_f_equals and g.config.freeze_formulas and g.config.run_up_to == 100
    assert g.config.extra == {"ParentSheet": "Parents", "CopyFormats": "False"} and g.config.use_parents
    assert rep.templates == 2 and rep.template_rows == 3 and rep.parents == 1
    assert rep.mapped_formulas == {"concat (&)": 3, "exists (EXACT/VLOOKUP approximate)": 3, "lookup (IF blank, VLOOKUP)": 2}
    assert [u.formula for u in rep.unmapped_formulas] == ["=SUM(F{row}:F{row})"]
    names = [c.name for c in g.output_columns]
    cc = g.output_columns[names.index("Cable Code")].computed
    assert cc == Concat(parts=[{"col": "Cable Range"}, " - ", {"col": "Size"}])
    assert g.output_columns[names.index("Code Check")].computed == Exists(value="Cable Code", table="Codes", column="A")
    v = g.templates[0].rows[0].cells[names.index("Voltage")]
    assert v.kind == "computed" and v.override is None
    assert isinstance(g.output_columns[names.index("Voltage")].computed, Lookup)  # mapped rows agree
    assert g.templates[1].rows[0].cells[names.index("Voltage")].kind == "formula"  # template 12: unmapped SUM

    r = build(g)
    get = lambda c: [row.cells[r.header.index(c)] for row in r.rows if row.run_row_id]  # noqa: E731
    assert get("Cable Number") == ["100LB01-P1", "100LB01-P2 to P6", "100LB01-P9"]
    assert get("From") == ["100-LB01", "100-LB01", "100-LB01"]
    assert get("From Location")[0] == "NORTH YARD LIGHTING BOARD"
    assert get("Length") == [70, 350, 10]
    assert get("Cable Code") == ["R230 - 2.5", "R230 - 2.5", "R230 - 4"]
    assert get("Code Check") == [True, True, True]
    assert get("Voltage")[:2] == ["LV", "LV"]
    assert get("Voltage")[2] == "=SUM(F4:F4)"  # unmapped formula: kept as text, flagged by the import
    assert r.stats.skipped == 1 and r.stats.processed == 2

    out = export_xlsx(r, g.config, tmp_path / "out.xlsx", build_id="b1")
    from openpyxl import load_workbook
    wb = load_workbook(out)
    ws = wb["Schedule"]
    assert [c.value for c in ws[1]][:3] == ["TEMPLATE", "Run Num", "Cable Number"]
    assert ws.freeze_panes == "A2" and ws.auto_filter.ref.startswith("A1:") and ws["A1"].font.b
    assert ws["C3"].value == "100LB01-P2 to P6" and ws["F3"].value == 350
    assert wb.properties.title == "Lighting Schedule"
    csv = export_csv(r, tmp_path / "out.csv")
    assert "100LB01-P2 to P6" in csv.read_text(encoding="utf-8-sig")
    g.config.doc_number, g.config.doc_revision = "3500-E-LS-001", "B"
    assert export_name(g.config, "dp") == "3500-E-LS-001_B Lighting Schedule.xlsx"
    g.config.doc_number = ""
    assert export_name(g.config, "dp").startswith("dp Output ")


def test_cli(tmp_path, capsys):
    src = tmp_path / "lighting_dp_generator_test.xlsx"
    make_workbook(src)
    gj, bj = tmp_path / "dp.json", tmp_path / "b.json"
    assert main(["import", str(src), "-o", str(gj), "--report", str(tmp_path / "rep.json")]) == 1  # one unmapped formula
    assert main(["check", str(gj)]) in (0, 1)
    assert main(["build", str(gj), "-o", str(bj)]) == 0
    assert "2 runs, 3 rows" in capsys.readouterr().out
    assert main(["build", str(gj), "--prev", str(bj), "--upto", "2"]) == 0
    assert "0 added, 1 removed, 0 changed" in capsys.readouterr().out
    assert main(["diff", str(bj), str(bj)]) == 0
    assert main(["export", str(bj), "--gen", str(gj), "-o", str(tmp_path / "x.csv")]) == 0


FIXTURES = Path(os.environ.get("GENERATOR_FIXTURES", Path(__file__).resolve().parents[2] / "samples" / "generators-local"))


@pytest.mark.skipif(not list(FIXTURES.glob("*.xlsm")), reason="generator workbooks not available (set GENERATOR_FIXTURES)")
def test_golden_workbooks():
    from workbench_core.generators.golden import run_golden
    cases = run_golden(FIXTURES)
    failed = [(c.workbook, c.failures) for c in cases if not c.passed]
    assert not failed, failed
    assert cases
