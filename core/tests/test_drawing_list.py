# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
from datetime import date, datetime

import pytest

from workbench_core.keylists.drawing_list import (FIELDS, HEADINGS, as_typed, check_drawings, equipment_warnings, link_problem,
                                                  parse_date, tags_of)
from workbench_core.keylists.enums import EnumItem, ProjectEnums, check_enums, default_enums, lookup
from workbench_core.refdata import RefValidationError


def test_the_enums_a_project_starts_with() -> None:
    e = default_enums()
    assert [(d.code, d.name) for d in e.disciplines] == [
        ("E", "Electrical"), ("I", "Instrumentation"), ("M", "Mechanical"), ("P", "Piping"), ("C", "Civil"), ("S", "Structural"),
        ("H", "HVAC"), ("PR", "Process"), ("G", "General")]
    assert [t.name for t in e.drawing_types][:3] == ["Single Line Diagram", "Schematic", "Termination Diagram"] and len(e.drawing_types) == 16
    assert [s.label() for s in e.drawing_statuses] == ["Draft", "IFR", "IFA", "IFT", "IFC", "AB", "Superseded", "Cancelled"]
    assert default_enums() == e and check_enums(e).model_dump(exclude={"updated_at"}) == e.model_dump(exclude={"updated_at"})
    assert lookup(e.drawing_statuses)["issued for construction"] == lookup(e.drawing_statuses)["ifc"] == "ds5"


def test_enum_rules() -> None:
    bad = ProjectEnums(
        disciplines=[EnumItem(id="a", code=" E ", name=" Electrical  works "), EnumItem(id="b", code="e", name="Elec"),
                     EnumItem(id="c", code="", name="No code"), EnumItem(id="d", code="X", name=" ")],
        drawing_types=[EnumItem(id="t1", name="Layout"), EnumItem(id="t2", name="layout")],
        drawing_statuses=[EnumItem(id="s1", code="IFC", name="For construction"), EnumItem(id="s2", name="Draft")])
    with pytest.raises(RefValidationError) as exc:
        check_enums(bad)
    assert exc.value.fields == {"b.code": "Code 'e' is used twice", "c.code": "A discipline needs a code", "d.name": "Name is required",
                                "t2.name": "Name 'layout' is used twice"}
    ok = check_enums(ProjectEnums(disciplines=bad.disciplines[:1], drawing_types=bad.drawing_types[:1], drawing_statuses=bad.drawing_statuses))
    assert (ok.disciplines[0].code, ok.disciplines[0].name) == ("E", "Electrical works")
    with pytest.raises(RefValidationError):  # an id used in two enums
        check_enums(ProjectEnums(disciplines=[EnumItem(id="x", code="E", name="E")], drawing_types=[EnumItem(id="x", name="L")]))


def test_dates() -> None:
    assert parse_date("14/03/2026") == parse_date("14-3-26") == parse_date("2026-03-14") == parse_date("14.03.2026") == date(2026, 3, 14)
    assert parse_date(datetime(2026, 3, 14, 9)) == parse_date(46095) == parse_date("46095.0") == date(2026, 3, 14)
    assert parse_date("") is None and parse_date(None) is None and parse_date("2026-03-14T00:00:00") == date(2026, 3, 14)
    for bad in ("soon", "31/02/2026", "14/03"):
        with pytest.raises(ValueError):
            parse_date(bad)


def test_drawings_are_checked_and_their_choices_resolved() -> None:
    enums = default_enums()
    assert FIELDS[0] == "number" and HEADINGS == [
        "Drawing number", "Project name", "Title 1", "Title 2", "Title 3", "Drawing discipline", "Drawing type", "Revision", "Status",
        "Issue date", "Vendor drg number", "Vendor reference", "Equipment reference", "Scope", "Hyperlink"]
    rows = [{"id": "d1", "number": " 3510-E-SLD-001 ", "project_name": "Plant A", "title_1": "MCC-1", "title_2": "Single line diagram",
             "discipline": "electrical", "drawing_type": "Single Line Diagram", "revision": 0, "status": "ifc", "issue_date": "14/03/2026",
             "vendor_drg_number": "V-100", "equipment_reference": "MCC-1 ; P-101,, X-9", "scope": "Detailed design"},
            {"id": "d2", "number": "3510-P-PID-507", "discipline_id": "d-pr", "status": "Issued for Review"},
            {"number": "3510-G-IDX-001"}]
    out = check_drawings(rows, enums).items
    first = out[0]
    assert (first.id, first.number, first.discipline_id, first.drawing_type_id, first.status_id, first.revision, first.issue_date) == (
        "d1", "3510-E-SLD-001", "d-e", "dt1", "ds5", "0", date(2026, 3, 14))
    assert first.equipment_reference == "MCC-1, P-101, X-9" and tags_of(first.equipment_reference) == ["MCC-1", "P-101", "X-9"]
    assert (out[1].discipline_id, out[1].status_id, out[1].drawing_type_id, out[1].issue_date) == ("d-pr", "ds2", None, None)
    assert out[2].id and out[2].discipline_id is None
    typed = as_typed(first, enums)
    assert (typed["discipline"], typed["drawing_type"], typed["status"], typed["issue_date"]) == ("E", "Single Line Diagram", "IFC", "14/03/2026")
    assert check_drawings([typed | {"id": "d1"}], enums).items[0] == first  # round trip
    assert equipment_warnings(first.equipment_reference, {"mcc-1", "p-101"}) == ["X-9"] and equipment_warnings("", set()) == []


def test_what_refuses_a_drawing_list() -> None:
    rows = [{"id": "a", "number": "D-1", "discipline": "Rocket science", "drawing_type": "Sketch", "status": "Done", "issue_date": "soon"},
            {"id": "b", "number": " d-1 "}, {"id": "c", "number": ""}, {"id": "d", "number": "D-2", "status_id": "gone"}]
    with pytest.raises(RefValidationError) as exc:
        check_drawings(rows, default_enums())
    assert set(exc.value.fields) == {"a.discipline", "a.drawing_type", "a.status", "a.issue_date", "b.number", "c.number", "d.status"}
    assert exc.value.fields["a.status"] == "'Done' is not a status of the project's Enums"
    with pytest.raises(RefValidationError):
        check_drawings([{"id": "a", "number": "1"}, {"id": "a", "number": "2"}], default_enums())


def test_a_drawing_has_a_hyperlink() -> None:
    for ok in ("", "https://dms.example.com/drawings/3510-E-SLD-001?rev=B", "http://server/x.pdf", "HTTPS://Server/x", "file:///C:/dwg/a.pdf",
               r"C:\Drawings\3510\a.pdf", r"\\server\share\3510\a.pdf", "/mnt/drawings/a.pdf", "drawings/a.pdf"):
        assert link_problem(ok) is None, ok
    for bad in ("javascript:alert(1)", "data:text/html,x", "https://", "ftp://server/a.pdf", "mailto:a@b.c"):
        assert link_problem(bad), bad
    rows = [{"id": "a", "number": "D-1", "hyperlink": "  https://dms.example.com/D-1  "}, {"id": "b", "number": "D-2", "hyperlink": "javascript:1"}]
    with pytest.raises(RefValidationError) as exc:
        check_drawings(rows, default_enums())
    assert set(exc.value.fields) == {"b.hyperlink"}
    saved = check_drawings(rows[:1], default_enums()).items[0]
    assert saved.hyperlink == "https://dms.example.com/D-1" and as_typed(saved, default_enums())["hyperlink"] == saved.hyperlink


def test_the_document_list_spec() -> None:
    from workbench_core.keylists.drawing_list import DOCUMENTS, DRAWINGS, REGISTERS
    assert list(REGISTERS) == ["drawing-list", "document-list"] and DRAWINGS.headings == HEADINGS
    assert [f for f in DOCUMENTS.fields if f.startswith("title")] == ["title"] and len(DOCUMENTS.fields) == len(DRAWINGS.fields) - 2
    enums = default_enums()
    assert len(enums.document_types) == 16 and enums.document_types[1].name == "Datasheet"
    docs = check_drawings([{"id": "a", "number": "S-1", "title": " Spec ", "discipline": "E", "document_type": "specification", "status": "IFC",
                            "issue_date": "01/02/2026", "vendor_doc_number": "V-9", "hyperlink": "https://x.example/s-1"}], enums, DOCUMENTS)
    d = docs.items[0]
    assert (type(d).__name__, d.title, d.discipline_id, d.document_type_id, d.status_id, d.vendor_doc_number) == (
        "Document", "Spec", "d-e", "doc1", "ds5", "V-9")
    assert as_typed(d, enums, DOCUMENTS)["document_type"] == "Specification"
    with pytest.raises(RefValidationError) as exc:
        check_drawings([{"id": "a", "number": "", "document_type": "Layout"}], enums, DOCUMENTS)
    assert exc.value.fields == {"a.number": "Document number is required",
                                "a.document_type": "'Layout' is not a document type of the project's Enums"}
    assert "Document List" in exc.value.message
