# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Engine rules on synthetic fixtures. All tags, descriptions and codes here are invented."""

import pytest

from gen_helpers import col, make_gen
from workbench_core.generators import NO_VALUE, PARENT_NOT_FOUND, BuildError, build
from workbench_core.generators.models import CablePrefix, Concat, DerivedTag, Exists, Lookup, RefTable, Route

# -- a two-row lighting circuit: late formulas, freeze, computed columns -----------------

LT_TAGS = ["<<Key>>", "<<SS>>", "<<Area>>", "<<RUN>>", "<<FromTag>>", "<<ToDesc>>", "<<LEN>>",
           "<<LEN2>>", "<<Qty>>", "<<CCT1>>", "<<CCT2>>", "<<Size>>", "<<Size2>>", "<<Fitting>>"]
LT_COLS = ["Related SWR", "Run Num", "Cable Number", "From", "From Location", "To", "To Location", "Length",
           "Cable Range", "Cable Type", "Cores", "Size", "Cable Code", "Code Check", "Voltage", "Type"]
JB = "<<ToDesc>> JUNCTION BOX <<FromTag_S>><<CCT1>><<CCT2>>-JB1"
LT_TPL = [
    ["<<SS>>", "<<RUN>>", "<<FromTag_S>><<CCT1>><<CCT2>>-P1", "<<FromTag>>", "<<FromTag_P>>", "<<Area>> AREA", JB,
     "<<LEN>>", "R230", "Pwr", "2C", "<<Size>>", "@computed", "@computed", "@computed", "@computed"],
    ["<<SS>>", "<<RUN>>", 'F="<<FromTag_S>><<CCT1>><<CCT2>>-P2 to P"& <<QTY>>+1', "<<Area>> AREA", JB,
     "<<Area>> AREA", "<<Fitting>> FITTINGS  (<<QTY>> UNITS, *NOMINAL LENGTH <<LEN2>>m PER CABLE)",
     "F=<<LEN2>>*<<QTY>>", "R230", "Pwr", "2C", "<<Size2>>", "@computed", "@computed", "@computed", "@computed"],
]
CODE = "R230 - Pwr - 2C - 2.5"


def lt_gen(**cfg):
    cfg = {"replace_f_equals": True, "freeze_formulas": True, "run_from": 0, "run_up_to": 100, **cfg}
    computed = {
        "Cable Code": Concat(parts=[{"col": "Cable Range"}, " - ", {"col": "Cable Type"}, " - ", {"col": "Cores"}, " - ", {"col": "Size"}]),
        "Code Check": Exists(value="Cable Code", table="Codes", column="C"),
        "Voltage": Lookup(key="Cable Code", table="Kinds", key_column="B", return_column="D", guard_column="Code Check"),
        "Type": Lookup(key="Cable Code", table="Kinds", key_column="B", return_column="E", guard_column="Code Check"),
    }
    g = make_gen(LT_TAGS, [[7, "SR-01", "100", 1, "100-LB01", "NORTH YARD LAMPS", 40, 12, 5, "AB", 3, 2.5, 2.5, "LAMP - POLE "]],
                 LT_COLS, {7: LT_TPL}, parents=[("100-LB01", "NORTH YARD LIGHTING BOARD")], computed=computed, **cfg)
    g.tables["Codes"] = RefTable(name="Codes", columns=list("ABC"),
                                 rows=[[None, None, v] for v in ["R230 - Pwr - 2C - 1.5", "R230 - Pwr - 2C - 10", CODE, "R230 - Pwr - 2C - 4"]])
    g.tables["Kinds"] = RefTable(name="Kinds", columns=list("ABCDE"),
                                 rows=[[None, "Code", None, "Volts", "Build"], [None, CODE, None, "LV", "CU-XLPE"]])
    return g


def test_lighting_circuit_two_rows():
    r = build(lt_gen())
    assert col(r, "Cable Number") == ["100LB01AB3-P1", "100LB01AB3-P2 to P6"]
    assert col(r, "From") == ["100-LB01", "100 AREA"]
    assert col(r, "From Location") == ["NORTH YARD LIGHTING BOARD", "NORTH YARD LAMPS JUNCTION BOX 100LB01AB3-JB1"]
    assert col(r, "To Location")[1] == "LAMP - POLE FITTINGS (5 UNITS, *NOMINAL LENGTH 12m PER CABLE)"  # spaces collapsed
    assert col(r, "Length") == [40, 60]  # late formula 12*5
    assert col(r, "Cable Code") == [CODE, CODE]
    assert col(r, "Code Check") == [True, True]
    assert col(r, "Voltage") == ["LV", "LV"] and col(r, "Type") == ["CU-XLPE", "CU-XLPE"]
    assert r.header[0] == "TEMPLATE" and r.rows[0].cells[0] == 7
    assert r.rows[0].template_id == "7" and r.rows[1].template_seq == 2 and r.rows[0].run_row_id == "3"


def test_code_check_miss_gives_false_then_na_lookup():
    g = lt_gen()
    g.runsheet.rows[0].values[11] = 99  # code not in the list
    r = build(g)
    assert col(r, "Code Check")[0] is False  # approximate match finds a different entry
    assert col(r, "Voltage")[0] == "#N/A"  # guard passes (FALSE <> ""), exact lookup misses


def test_code_check_standard_mode_is_exact():
    g = lt_gen(mode="standard")
    g.tables["Codes"].rows.reverse()  # unsorted: approximate match would be unreliable
    assert col(build(g), "Code Check") == [True, True]


def test_freeze_off_keeps_values():
    assert col(build(lt_gen(freeze_formulas=False)), "Length") == [40, 60]


def test_late_formula_stays_text_without_replace_f_equals():
    assert col(build(lt_gen(replace_f_equals=False)), "Length")[1] == "F=12*5"


# -- device list: <<PARENT>> with ParentIncludeTag -----------------------------------------

DEV_TAGS = ["<<Key>>", "<<ID>>", "<<RUN>>", "<<MECH>>", "<<SUF>>", "<<#1>>", "<<#2>>"]
DEV_COLS = ["Run", "Tag", "Parent", "Description", "Make"]
DEV_TPL = [["<<RUN>>", "<<MECH>>-CP1", "<<PARENT>>", "CONTROL PANEL", "MakerA"],
           ["<<RUN>>", "XA<<#1>>", "<<PARENT>>", "Alarm horn", "MakerB"],
           ["<<RUN>>", "QH<<#1>>", "<<PARENT>>", "SWITCH HIGH", "MakerC"]]
PARENTS = [("200-PS01", "WEST PUMP STATION")]


def dev_gen(runs=None, **cfg):
    runs = runs or [[4, 1, 9, "200-PS01", " ", 7001, None]]
    cfg = {"parent_include_tag": True, "diff_key": "Tag", "run_column": "Run", **cfg}
    return make_gen(DEV_TAGS, runs, DEV_COLS, {4: DEV_TPL}, parents=PARENTS, **cfg)


def test_device_list_parent_include_tag():
    r = build(dev_gen())
    assert col(r, "Tag") == ["200-PS01-CP1", "XA7001", "QH7001"]
    assert set(col(r, "Parent")) == {"WEST PUMP STATION (200-PS01) "}  # trailing space kept (D13)
    assert col(r, "Run") == [9, 9, 9]


def test_parent_variants():
    g = dev_gen(runs=[[4, 1, 9, "200-PS01", "SUMP", 1, None]], parent_include_tag=False)
    assert col(build(g), "Parent")[0] == "WEST PUMP STATIONSUMP"  # p + SUF, no separator
    g = dev_gen(runs=[[4, 1, 9, "999-ZZ", "SUMP", 1, None]])
    assert col(build(g), "Parent")[0] == "SUMP"  # parent not found: SUF only
    g = dev_gen(runs=[[4, 1, 9, "999-ZZ", None, 1, None]])
    assert col(build(g), "Parent")[0] == NO_VALUE
    g = dev_gen(runs=[[4, 1, 9, "200-ps01", " ", 1, None]])
    assert col(build(g), "Parent")[0] == " "  # compat: case-sensitive parent lookup (D5)
    g = dev_gen(runs=[[4, 1, 9, "200-ps01", " ", 1, None]], mode="standard")
    assert col(build(g), "Parent")[0] == "WEST PUMP STATION (200-ps01) "  # trimmed (D13), then SUF " "


def test_suffix_p_tag_and_parent_not_found():
    g = make_gen(["<<Key>>", "<<RUN>>", "<<FromTag>>"], [[1, 1, "A-1"], [1, 2, "B-2"]], ["Run Num", "Desc", "Sq"],
                 {1: [["<<RUN>>", "<<FromTag_P>>", "<<FromTag_S>>"]]}, parents=[("A-1", "ALPHA"), ("A-1", "DUP")])
    r = build(g)
    assert col(r, "Desc") == ["ALPHA", PARENT_NOT_FOUND]
    assert col(r, "Sq") == ["A1", "B2"]
    assert any(w.code == "duplicateParents" for w in r.warnings)


def test_io_list_loop_numbers():
    rows = [["<<RUN>>", "ISOLATOR CLOSED", "DI-32", None, "XI<<#2>>"],
            ["<<RUN>>", "RUNNING", "DI-32", None, "XI<<#1>>"],
            ["<<RUN>>", "FLOW", "AI-8", 2, "QF<<#1>>"]]
    g = make_gen(["<<Key>>", "<<RUN>>", "<<#1>>", "<<#2>>"], [[2, 1, 8101, 8102]],
                 ["Run", "Signal", "CARD TYPE", "# Wire", "IO v1"], {2: rows}, run_column="Run")
    r = build(g)
    assert col(r, "IO v1") == ["XI8102", "XI8101", "QF8101"]
    assert col(r, "# Wire") == [None, None, 2]


# -- lookups that return tags: freeze, then expand again ---------------------------------

def test_lookup_results_expanded_again_when_frozen():
    tags = ["<<Key>>", "<<STD>>", "<<RUN>>", "<<MECH>>", "<<DESC>>", "<<SUF>>", "<<PNL>>", "<<DB>>"]
    cols = ["Run Num", "Cable Number", "From", "From Location", "To", "To Location", "From Device", "To Device"]
    lk = lambda key, n: Lookup(key=key, table="Devices", key_column="A", return_column=n, guard_column=key)  # noqa: E731
    computed = {"From": lk("From Device", "C"), "From Location": lk("From Device", "D"),
                "To": lk("To Device", "C"), "To Location": lk("To Device", "D")}
    c = "@computed"
    tpl = [["<<RUN>>", "<<MECH_S>>-P1", c, c, c, c, "K1-<<DB>>", "K1-<<MECH_S>>-Q1"],
           ["<<RUN>>", "<<MECH_S>>-C1", c, c, c, c, "K1-<<PNL>>", "K1-<<MECH_S>>-JB1"],
           ["<<RUN>>", "<<MECH_S>>-X1", c, c, c, c, None, "K1-<<MECH_S>>-JB1"]]
    g = make_gen(tags, [[2, "K1", 1, "300-PM01", "EAST PUMP", "SUMP", "300-CP01", "300-DB01"]], cols, {"K1": tpl},
                 parents=[("300-DB01", "DB ONE"), ("300-CP01", "PANEL ONE")], computed=computed,
                 key_placeholder="<<STD>>", freeze_formulas=True)
    g.tables["Devices"] = RefTable(name="Devices", columns=list("ABCD"), rows=[
        ["K1-<<DB>>", "K1", "<<DB>>", "<<DB_P>>"],
        ["K1-<<PNL>>", "K1", "<<PNL>>", "<<PNL_P>>"],
        ["K1-<<MECH_S>>-Q1", "K1", "<<MECH_S>>-Q1", "<<DESC>> <<SUF>> ISOLATOR"],
        ["K1-<<MECH_S>>-JB1", "K1", "<<MECH_S>>-JB1", "<<DESC>> <<SUF>> JUNCTION BOX"]])
    for oc in g.output_columns[6:]:
        oc.raw = True  # device keys are tag patterns, looked up unexpanded
    r = build(g)
    assert col(r, "Cable Number") == ["300PM01-P1", "300PM01-C1", "300PM01-X1"]
    assert col(r, "From") == ["300-DB01", "300-CP01", ""]
    assert col(r, "From Location") == ["DB ONE", "PANEL ONE", ""]
    assert col(r, "To") == ["300PM01-Q1", "300PM01-JB1", "300PM01-JB1"]
    assert col(r, "To Location") == ["EAST PUMP SUMP ISOLATOR", "EAST PUMP SUMP JUNCTION BOX", "EAST PUMP SUMP JUNCTION BOX"]
    g.config.freeze_formulas = False
    assert col(build(g), "To")[0] == "<<MECH_S>>-Q1"


# -- tags, values and typing --------------------------------------------------------------

def simple(tags, runs, cells, cols=None, **cfg):
    cols = cols or [f"C{i}" for i in range(len(cells))]
    return make_gen(tags, runs, cols, {1: [cells]}, **cfg)


def test_case_insensitive_and_prefix_tags():
    tags = ["<<Key>>", "<<Qty>>", "<<LEN>>", "<<LEN2>>", "<<#1>>", "<<#10>>"]
    g = simple(tags, [[1, 5, 70, 15, "A", "J"]], ["<<QTY>>|<<qty>>", "<<LEN>>-<<LEN2>>", "<<#1>>/<<#10>>"])
    assert build(g).rows[0].cells[1:] == ["5|5", "70-15", "A/J"]


def test_blank_values_become_no_value():
    g = simple(["<<Key>>", "<<A>>", "<<B>>"], [[1, None, "x-y"]], ["<<A>>", "<<A_S>>", "<<B_S>>"])
    assert build(g).rows[0].cells[1:] == [NO_VALUE, NO_VALUE, "xy"]


def test_as_typed_output_and_literal_protection():
    g = simple(["<<Key>>", "<<N>>", "<<B>>"], [[1, "75", "true"]], ["<<N>>", "<<B>>", "35", 35, "x<<N>>"])
    assert build(g).rows[0].cells[1:] == [75, True, "35", 35, "x75"]


def test_collapse_spaces_and_f_equals_rules():
    g = simple(["<<Key>>", "<<A>>"], [[1, "a "]], ["<<A>> b", "x  y", "aF=1"], collapse_spaces=True, replace_f_equals=True)
    assert build(g).rows[0].cells[1:] == ["a b", "x y", "a=1"]  # compat: F= replaced anywhere (D8)
    g.config.mode = "standard"
    assert build(g).rows[0].cells[3] == "aF=1"
    g.config.collapse_spaces = False
    g.config.mode = "compat"
    assert build(g).rows[0].cells[1] == "a  b"


def test_values_containing_tags_expand_further():
    g = simple(["<<Key>>", "<<A>>", "<<B>>"], [[1, "<<B>>!", "bee"]], ["<<A>>"])
    assert build(g).rows[0].cells[1] == "bee!"  # D4: inserted as-is, later tags expand it


def test_derived_tags():
    tags = ["<<Key>>", "<<FROM>>", "<<TO>>", "<<CT>>"]
    g = simple(tags, [[1, "sw-1", "mcc-2", "R230"]],
               ["<<UP>>", "<<L2>>", "<<CAT>>", "<<LEN>>", "<<PFX>>", "<<SEQ>>", "<<FIX>>", "<<EMPTY>>"])
    g.derived_tags = [DerivedTag(name="UP", source="<<FROM>>", transform="upper"),
                      DerivedTag(name="<<L2>>", source="<<TO>>", transform="left:3"),
                      DerivedTag(name="CAT", source="<<FROM>>", transform="concat:<<TO>>"),
                      DerivedTag(name="LEN", source="<<TO>>", transform="route:<<FROM>>"),
                      DerivedTag(name="PFX", source="<<CT>>", transform="prefix"),
                      DerivedTag(name="SEQ", source="", transform="seq"),
                      DerivedTag(name="FIX", source="", transform="fixed", default="F"),
                      DerivedTag(name="EMPTY", source="<<TO>>", transform="right:0", default="dflt")]
    g.routes = [Route(a="SW-1", b="MCC-2", length=42)]
    g.cable_prefixes = [CablePrefix(cable_type="R230", prefix="P")]
    assert build(g).rows[0].cells[1:] == ["SW-1", "mcc", "sw-1mcc-2", 42, "P", 1, "F", "dflt"]


# -- run selection ------------------------------------------------------------------------

def runs_gen(runs, **cfg):
    return make_gen(["<<Key>>", "<<RUN>>"], runs, ["Run Num"], {1: [["<<RUN>>"]], 2: [["<<RUN>>"], ["<<RUN>>"]]}, **cfg)


def test_run_filter_bounds():
    runs = [[1, 9], [1, 10], [1, 19], [1, 20], [1, "abc"], [1, None]]
    assert col(build(runs_gen(runs, run_from=10, run_up_to=20)), "Run Num") == [10, 19]  # up-to exclusive
    r = build(runs_gen(runs, run_from=0, run_up_to=1))
    assert col(r, "Run Num") == ["abc", NO_VALUE]  # non-numeric and blank run count as 0 (D3)
    assert build(runs_gen(runs), run_from=19).stats.processed == 2


def test_run_filter_without_run_column_is_fatal():
    g = make_gen(["<<Key>>"], [[1]], ["X"], {1: [["a"]]}, run_from=1)
    with pytest.raises(BuildError, match="run selection"):
        build(g)


def test_nr_none_blank_and_stop_at_blank_key():
    runs = [[1, 1], ["NR", 2], ["none", 3], [None, 4], [2, 5], [7, 6]]
    r = build(runs_gen(runs))
    assert col(r, "Run Num") == [1, 5, 5]
    assert (r.stats.skipped, r.stats.blank_key, r.stats.no_template, r.stats.processed) == (2, 1, 1, 2)
    assert r.stats.output_rows == 4  # one separator between runs, none after the last
    assert any(w.code == "missingTemplate" and "7 (run 6)" in w.detail for w in r.warnings)
    assert col(build(runs_gen(runs, stop_at_blank_key=True)), "Run Num") == [1]


def test_no_separator_rows_when_disabled():
    assert build(runs_gen([[1, 1], [1, 2]], blank_row_between_runs=False)).stats.output_rows == 2


def test_duplicate_tags_are_fatal_and_no_tags():
    with pytest.raises(BuildError, match="duplicate tag"):
        build(make_gen(["<<Key>>", "<<key>>"], [[1, 1]], ["X"], {1: [["a"]]}))
    with pytest.raises(BuildError, match="no <<tags>>"):
        build(make_gen(["Key"], [[1]], ["X"], {1: [["a"]]}))


def test_key_placeholder_falls_back_to_first_tag():
    g = make_gen(["<<ID>>", "<<RUN>>"], [[1, 3]], ["Run Num"], {1: [["<<RUN>>"]]})
    assert col(build(g), "Run Num") == [3]


def test_duplicate_template_ids_first_block_wins():
    from workbench_core.generators.models import Template, TemplateCell, TemplateRow
    g = runs_gen([[1, 1]])
    g.templates.append(Template(id="1", id_value=1, rows=[TemplateRow(cells=[TemplateCell(kind="literal", value="second")])]))
    r = build(g)
    assert col(r, "Run Num") == [1]
    assert any(w.code == "duplicateTemplateIds" for w in r.warnings)


# -- locked runs, change report, determinism ---------------------------------------------

def test_locked_runs():
    tags = ["<<Key>>", "<<RUN>>", "<<V>>", "<<LOCKED>>"]
    g = make_gen(tags, [[1, 1, "a", None], [1, 2, "b", None]], ["Run Num", "Cable Number"], {1: [["<<RUN>>", "<<V>>-<<RUN>>"]]})
    first = build(g)
    g.runsheet.rows[0].values[2:4] = ["changed", "TRUE"]
    g.runsheet.rows[1].values[2] = "z"
    r = build(g, previous=first)
    assert col(r, "Cable Number") == ["a-1", "z-2"]
    assert r.rows[0].locked and r.stats.locked_used == 1
    assert (r.changes.added, r.changes.removed, r.changes.changed) == (1, 1, 0)
    r = build(g)  # no previous build: regenerate and warn
    assert col(r, "Cable Number")[0] == "changed-1"
    assert any(w.code == "lockedNotFound" for w in r.warnings)


def test_rebuild_reports_no_changes_and_is_deterministic():
    g = lt_gen()
    a = build(g)
    b = build(g, previous=a)
    assert (b.changes.added, b.changes.removed, b.changes.changed) == (0, 0, 0)
    strip = lambda r: r.model_dump_json(exclude={"stats": {"duration_ms", "phase_ms"}, "changes": True})  # noqa: E731
    assert strip(a) == strip(build(g))


def test_unresolved_tokens_and_row_directives():
    g = make_gen(["<<Key>>", "<<Prev>>"], [[1, "<<DELETE ROW>>"]], ["A", "B"], {1: [["<<Prev>>", "<<Nope>>"], ["ok", "ok"]]})
    r = build(g)
    assert r.unresolved_count == 2 and r.unresolved_tokens == ["<<DELETE ROW>>", "<<Nope>>"]
    assert r.stats.rows_written == 2  # compat: the directive passes through (D9)
    g.config.mode = "standard"
    r = build(g)
    assert r.stats.deleted_rows == 1 and r.stats.rows_written == 1
    g.runsheet.rows[0].values[1] = "<<MANUAL ROW>>"
    r = build(g)
    assert r.stats.rows_written == 2 and any(w.code == "manualRow" for w in r.warnings)
