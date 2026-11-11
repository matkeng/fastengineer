# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")
pytest.importorskip("pypdfium2")

from workbench_core.symbols import (  # noqa: E402
    Exclusion,
    Library,
    PageOverride,
    SheetResult,
    Symbol,
    TagPoint,
    Template,
    Variants,
    Word,
    analyse_page,
    choose_words,
    tags_table,
)
from workbench_core.symbols.export import tags_csv, tags_xlsx  # noqa: E402
from workbench_core.symbols.match import locate_symbols, nms, prepare  # noqa: E402
from workbench_core.symbols.render import PdfError, decode_gray, page_count, render_pages  # noqa: E402
from workbench_core.symbols.starter import STARTER_LIBRARY  # noqa: E402
from workbench_core.symbols.tags import (  # noqa: E402
    TagRules,
    apply_exclusion,
    box_overlap,
    check_format,
    compile_pattern,
    format_tag,
    group_names,
    pattern_scan,
    point_in_symbol,
    resolve_points,
)
from workbench_core.symbols.templates import effective_mask, make_mask, trim  # noqa: E402

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
EXPECTED = {"FV-1023", "FV-1024", "FT-1023", "PT-1025", "TT-1026A", "LIC-1030", "PI-1041", "PSV-1040",
            "FT-2001", "PT-2002", "FV-2001"}


def _starter():
    # with the text scan switched on (it is off in a new library): these tests are about what it finds
    lib = Library(id="L", **(STARTER_LIBRARY["library"] | {"pattern_scan": True}))
    out = []
    for i, raw in enumerate(STARTER_LIBRARY["templates"]):
        raw = dict(raw)
        g = decode_gray(base64.b64decode(raw.pop("image_png")))
        out.append(prepare(Template(id=f"t{i}", library_id="L", width=g.shape[1], height=g.shape[0], **raw), g))
    return out, lib


@pytest.fixture(scope="module")
def pages():
    return list(render_pages((SAMPLES / "pid-sample.pdf").read_bytes()))


@pytest.fixture(scope="module")
def results(pages):
    tis, lib = _starter()
    return [analyse_page(p.n, decode_gray(p.png), p.words, "pdf", tis, {}, lib) for p in pages]


def test_render_puts_words_in_the_image_frame(pages) -> None:
    p1, p2 = pages
    assert (p1.width_px, p1.height_px, p1.rotation) == (3309, 2339, 0)
    assert (p2.width_px, p2.height_px, p2.rotation) == (2339, 3309, 90)  # /Rotate applied: portrait
    assert [w.text for w in p1.words][:4] == ["FV", "1023", "FV", "1024"]
    assert "PSV-1040" in [w.text for w in p1.words] and "DRAWING" in [w.text for w in p1.words]
    for p in pages:
        gray = decode_gray(p.png)
        assert gray.shape == (p.height_px, p.width_px)
        for w in p.words:
            x1, y1, x2, y2 = (int(v) for v in w.box)
            assert 0 <= x1 < x2 <= p.width_px and 0 <= y1 < y2 <= p.height_px
            assert (x2 - x1) > (y2 - y1) * 0.6 or len(w.text) <= 2  # upright text, also on the rotated sheet
            assert gray[y1:y2 + 1, x1:x2 + 1].min() < 128  # there is ink under every word box


def test_bad_pdf() -> None:
    with pytest.raises(PdfError):
        page_count(b"not a pdf")


def test_masks_auto_custom_none() -> None:
    img = np.full((40, 40), 255, np.uint8)
    cv2.line(img, (5, 20), (35, 20), 0, 1)
    thin, wide = make_mask(img, 1), make_mask(img, 4)
    assert (wide[:, 20] > 0).sum() > (thin[:, 20] > 0).sum() >= 1
    assert trim(img).shape[0] < 10 and trim(img).shape[1] >= 30
    assert effective_mask("none", img, 2) is None
    custom = np.zeros((20, 20), np.uint8)
    custom[:10] = 200  # top half, at a different size: resized to the template
    m = effective_mask("custom", img, 2, custom)
    assert m.shape == img.shape and set(np.unique(m)) == {0, 255}
    assert m[:20].all() and not m[20:].any()
    assert (effective_mask("auto", img, 4) == wide).all()


def test_custom_mask_ignores_what_it_leaves_out() -> None:
    """A template whose lower half is masked out matches symbols that differ only there."""
    page = np.full((300, 400), 255, np.uint8)
    for x, extra in ((80, False), (260, True)):
        cv2.rectangle(page, (x, 100), (x + 60, 130), 0, 2)
        if extra:
            cv2.line(page, (x + 5, 150), (x + 55, 150), 0, 2)  # only the second has a bar below
        cv2.rectangle(page, (x, 100), (x + 60, 130), 0, 2)
    tpl = page[90:165, 70:150].copy()  # cut from the first one (no bar)
    t = Template(id="r", library_id="L", desc="box", width=tpl.shape[1], height=tpl.shape[0], mask_mode="none",
                 threshold=0.9)
    assert len(locate_symbols(page, [prepare(t, tpl)]).symbols) == 1
    custom = np.zeros(tpl.shape, np.uint8)
    custom[:48] = 255  # compare only the box, not the area below it
    t2 = t.model_copy(update={"mask_mode": "custom"})
    assert len(locate_symbols(page, [prepare(t2, tpl, custom)]).symbols) == 2


def test_box_overlap_uses_the_smaller_box() -> None:
    assert box_overlap([0, 0, 100, 100], [10, 10, 20, 20]) == 1.0
    assert box_overlap([0, 0, 10, 10], [5, 0, 15, 10]) == 0.5
    assert box_overlap([0, 0, 10, 10], [20, 20, 30, 30]) == 0.0


def test_p_and_id_example_finds_every_tag(results) -> None:
    tis, lib = _starter()
    headers, rows = tags_table([SheetResult("pid-sample.pdf", r) for r in results], group_names(lib))
    assert headers == ["Tag", "function", "loop", "suffix", "Count", "Drawings", "Sheets", "Symbols", "Source"]
    assert {r["Tag"] for r in rows} == EXPECTED
    ft = next(r for r in rows if r["Tag"] == "FT-1023")
    assert ft["Count"] == "2" and ft["Sheets"] == "pid-sample.pdf p1; pid-sample.pdf p2"
    assert ft["Source"] == "template" and ft["Symbols"] == "Instrument bubble"
    tt = next(r for r in rows if r["Tag"] == "TT-1026A")
    assert (tt["function"], tt["loop"], tt["suffix"]) == ("TT", "1026", "A")
    assert next(r for r in rows if r["Tag"] == "PSV-1040")["Source"] == "text scan"


def test_priority_whiteout_and_no_duplicates(results) -> None:
    kinds = [s.template_desc for s in results[0].symbols]
    assert kinds.count("Instrument bubble") == 7
    assert kinds.count("Control valve") == 2
    assert kinds.count("Valve") == 2  # the control valves' bodies were erased before 'Valve' ran
    boxes = [s.box for s in results[0].symbols]
    assert len(nms([(1.0, b, "0") for b in boxes])) == len(boxes)


def test_ignored_area_removes_title_block_text(pages, results) -> None:
    tags = {t.tag for r in results for t in r.tags}
    assert "PID-100" not in tags and "SHT-01" not in tags
    tis, lib = _starter()
    raw = lib.model_copy(update={"exclusion": Exclusion()})
    p1 = pages[0]
    out = analyse_page(1, decode_gray(p1.png), p1.words, "pdf", tis, {}, raw)
    assert {"PID-100", "SHT-01"} <= {t.tag for t in out.tags}


def test_page_overrides_threshold_and_ignore(pages) -> None:
    tis, lib = _starter()
    p1 = pages[0]
    gray = decode_gray(p1.png)
    bubble = tis[0].template.id
    ignored = analyse_page(1, gray, p1.words, "pdf", tis, {bubble: PageOverride(template_id=bubble, ignore=True)}, lib)
    assert not any(s.template_desc == "Instrument bubble" for s in ignored.symbols)
    assert {t.tag for t in ignored.tags} >= {"FT-1023", "LIC-1030"}  # the text scan still reads them
    strict = analyse_page(1, gray, p1.words, "pdf", tis, {bubble: PageOverride(template_id=bubble, threshold=0.99)}, lib)
    assert sum(s.template_desc == "Instrument bubble" for s in strict.symbols) == 1


def test_too_many_hits_is_reported_not_silent(pages) -> None:
    tis, lib = _starter()
    tis[2].template.max_hits = 1
    p1 = pages[0]
    res = analyse_page(1, decode_gray(p1.png), p1.words, "pdf", tis, {}, lib)
    assert [s.desc for s in res.skipped] == ["Valve"]
    assert "Valve" in res.warnings[0] and "raise the threshold" in res.warnings[0]


def test_downscale_guard_keeps_boxes_in_full_size_pixels(monkeypatch) -> None:
    from workbench_core.symbols import match
    img = np.full((600, 800), 255, np.uint8)
    cv2.circle(img, (400, 300), 40, 0, 2)
    t = img[255:346, 355:446].copy()
    tmpl = prepare(Template(id="c", library_id="L", desc="circle", width=t.shape[1], height=t.shape[0]), t)
    full = locate_symbols(img, [tmpl]).symbols
    monkeypatch.setattr(match, "MAX_PIXELS", 120_000)  # forces scale 0.5
    scaled = locate_symbols(img, [tmpl]).symbols
    assert len(full) == len(scaled) == 1
    assert all(abs(a - b) <= 3 for a, b in zip(full[0].box, scaled[0].box)), (full[0].box, scaled[0].box)


def test_rotated_variant_and_tag_points_follow_rotation() -> None:
    t = Template(id="x", library_id="L", width=40, height=20, points=[TagPoint(name="P", x=30, y=5)])
    assert point_in_symbol(t, "0", 30, 5) == (30, 5)
    assert point_in_symbol(t, "90", 30, 5) == (15, 30)
    assert point_in_symbol(t, "180", 30, 5) == (10, 15)
    assert point_in_symbol(t, "270", 30, 5) == (5, 10)
    assert point_in_symbol(t, "0m", 30, 5) == (10, 5)
    assert point_in_symbol(t, "0@2", 30, 5) == (60, 10)
    img = np.full((300, 300), 255, np.uint8)
    arrow = np.full((30, 60), 255, np.uint8)
    cv2.line(arrow, (5, 15), (55, 15), 0, 2)
    cv2.line(arrow, (40, 5), (55, 15), 0, 2)
    cv2.line(arrow, (40, 25), (55, 15), 0, 2)
    img[50:80, 50:110] = arrow
    img[150:210, 200:230] = np.rot90(arrow, -1)
    tpl = Template(id="a", library_id="L", desc="arrow", width=60, height=30, variants=Variants(rot90=True))
    assert sorted(s.variant for s in locate_symbols(img, [prepare(tpl, arrow)]).symbols) == ["0", "90"]


def test_resolve_points_and_tag_format() -> None:
    t = Template(id="b", library_id="L", width=100, height=100, tag_format="{Function}-{Number}",
                 points=[TagPoint(name="Function", x=50, y=35), TagPoint(name="Number", x=50, y=65)])
    s = Symbol(template_id="b", template_desc="bubble", box=[1000, 1000, 1100, 1100], score=0.9)
    words = [Word(text="FT", box=[1040, 1028, 1060, 1042]), Word(text="1023", box=[1030, 1058, 1070, 1072]),
             Word(text="NOISE", box=[1095, 1030, 1200, 1040])]
    parts = resolve_points(s, t, words)
    assert parts == {"Function": "FT", "Number": "1023"}
    assert format_tag(t, parts) == "FT-1023"
    assert format_tag(t, {"Function": "FT", "Number": None}) == "FT"
    assert format_tag(t, {"Function": None, "Number": None}) is None
    assert format_tag(t.model_copy(update={"tag_format": ""}), parts) == "FT-1023"
    assert check_format("{Function}-{Num}", ["Function", "Number"]).startswith("{Num}")


def test_isa_text_scan_single_and_stacked() -> None:
    _, lib = _starter()
    rules = TagRules(lib)
    words = [Word(text="PT", box=[100, 100, 120, 112]), Word(text="101A", box=[96, 116, 126, 128]),
             Word(text="FIC-2002.", box=[300, 100, 360, 112]), Word(text="1234", box=[500, 100, 530, 112]),
             Word(text="NOTE", box=[600, 100, 640, 112]), Word(text="12", box=[600, 116, 615, 128])]
    tags = {t.tag: t for t in pattern_scan(words, rules, 1)}
    assert set(tags) == {"PT-101A", "FIC-2002", "NOTE-12"}
    assert tags["PT-101A"].groups == {"function": "PT", "loop": "101", "suffix": "A"}
    ex = Exclusion(words=["note"], areas=[])
    assert "NOTE-12" not in {t.tag for t in pattern_scan(apply_exclusion(words, ex, 1000, 1000), rules)}
    no_stack = lib.model_copy(update={"scan_stacked": False})
    assert {t.tag for t in pattern_scan(words, TagRules(no_stack))} == {"FIC-2002"}
    assert pattern_scan(words, TagRules(lib.model_copy(update={"pattern_scan": False}))) == []


def test_a_non_pid_library_with_its_own_tag_rules() -> None:
    """Any drawing type: e.g. cable tags like C-0412 or W12, formatted with a prefix."""
    lib = Library(id="C", name="Cables", tag_pattern=r"(?P<kind>C|W)-?(?P<num>\d{2,4})", tag_format="{kind}-{num:0>4}", pattern_scan=True)
    assert group_names(lib) == ["kind", "num"]
    words = [Word(text="C412", box=[0, 0, 30, 10]), Word(text="W-12", box=[50, 0, 80, 10]),
             Word(text="FT-1023", box=[100, 0, 140, 10])]
    assert [(t.tag, t.groups) for t in pattern_scan(words, TagRules(lib))] == [
        ("C-0412", {"kind": "C", "num": "412"}), ("W-0012", {"kind": "W", "num": "12"})]
    free = Library(id="F", name="Anything")  # no pattern: template tags as written, no text scan
    assert TagRules(free).normalise("ANY TEXT 1") == ("ANY TEXT 1", {})
    assert pattern_scan(words, TagRules(free)) == []
    with pytest.raises(ValueError):
        compile_pattern("[A-Z")


class FakeOcr:
    name = "Fake OCR"

    def __init__(self, words):
        self.words = words
        self.calls = 0

    def read(self, gray):
        self.calls += 1
        return self.words


def test_ocr_fallback_only_without_a_text_layer(pages) -> None:
    _, lib = _starter()
    p1 = pages[0]
    gray = decode_gray(p1.png)
    fake = FakeOcr(p1.words)
    words, src, warn = choose_words(gray, p1.words, lib, False, lambda: (fake, None))
    assert (src, fake.calls, warn) == ("pdf", 0, [])
    words, src, warn = choose_words(gray, [], lib, False, lambda: (fake, None))
    assert (src, fake.calls, len(words)) == ("ocr", 1, len(p1.words))
    assert choose_words(gray, p1.words, lib, True, lambda: (fake, None))[1] == "ocr"  # forced
    words, src, warn = choose_words(gray, [], lib, False, lambda: (None, "not on Windows"))
    assert src == "none" and "OCR is unavailable: not on Windows" in warn[0]


def test_scanned_sample_with_ocr_words_finds_the_tags(pages) -> None:
    tis, lib = _starter()
    scanned = list(render_pages((SAMPLES / "pid-sample-scanned.pdf").read_bytes()))
    assert all(not p.words for p in scanned)
    sheets = []
    for sp, tp in zip(scanned, pages):
        gray = decode_gray(sp.png)
        words, src, _ = choose_words(gray, sp.words, lib, False, lambda: (FakeOcr(tp.words), None))
        sheets.append(SheetResult("scan.pdf", analyse_page(sp.n, gray, words, src, tis, {}, lib)))
    assert {r["Tag"] for r in tags_table(sheets)[1]} == EXPECTED


def test_exports(results) -> None:
    sheets = [SheetResult("pid-sample.pdf", r) for r in results]
    csv_text = tags_csv(sheets, ["function", "loop"]).decode("utf-8-sig")
    assert csv_text.splitlines()[0] == "Tag,function,loop,Count,Drawings,Sheets,Symbols,Source"
    from openpyxl import load_workbook
    wb = load_workbook(BytesIO(tags_xlsx(sheets, "test")))
    assert wb.sheetnames == ["Tags", "Detections", "About"]
    assert wb["Tags"].max_row == len(EXPECTED) + 1


def test_ocr_tiles_upscale_and_map_boxes_back() -> None:
    """Words come back in page pixels, once each, across tiles of the upscaled page."""
    import asyncio

    from workbench_core.symbols.ocr import clean_ocr_text, ocr_tiles

    page = np.full((400, 1000), 255, np.uint8)
    # Two 'words' (in page pixels): one inside the first tile, one in the overlap of two tiles.
    targets = {"FT": (100, 50, 130, 62), "1O23": (590, 300, 630, 312)}
    for x1, y1, x2, y2 in targets.values():
        page[y1:y2, x1:x2] = 0
    scale = 3.0

    async def read_tile(png: bytes):
        tile = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_GRAYSCALE)
        out = []
        n, _, stats, _ = cv2.connectedComponentsWithStats((tile < 128).astype(np.uint8))
        for i in range(1, n):
            x, y, w, h, _ = stats[i]
            # identify the blob by its size in page pixels
            text = "FT" if abs(w / scale - 30) < 3 else "1O23"
            out.append((text, x, y, w, h))
        out.append(("--", 0, 0, 3, 3))  # junk is dropped
        return out

    words = asyncio.run(ocr_tiles(page, read_tile, tile=1800, scale=scale))
    got = sorted((w.text, [round(v) for v in w.box]) for w in words)
    assert got == [("1023", [590, 300, 630, 312]), ("FT", [100, 50, 130, 62])]
    assert clean_ocr_text(" FIC-2O02 ") == "FIC-2002" and clean_ocr_text("--") is None
    assert clean_ocr_text("|T-101") == "IT-101" and clean_ocr_text("POWER") == "POWER"


def test_text_only_removes_linework_and_keeps_text(pages) -> None:
    from workbench_core.symbols.ocr import merge_words, text_only

    p1 = pages[0]
    gray = decode_gray(p1.png)
    clean = text_only(gray)
    ink = (clean < 128).astype(np.uint8)
    n, _, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    assert all(stats[i][2] <= 60 and stats[i][3] <= 60 for i in range(1, n))  # no circles, pipes, valves
    for w in p1.words:  # every piece of text survives
        x1, y1, x2, y2 = (int(v) for v in w.box)
        assert clean[y1:y2 + 1, x1:x2 + 1].min() < 128, w.text
    # the bubble circle around FT/1023 is gone
    ft = next(w for w in p1.words if w.text == "FT")
    cx = int((ft.box[0] + ft.box[2]) / 2)
    ring_row = int(ft.box[1]) - 25
    assert clean[ring_row - 6:ring_row + 6, cx - 3:cx + 4].min() == 255

    a = [Word(text="FT", box=[0, 0, 10, 10])]
    b = [Word(text="F7", box=[1, 1, 10, 10]), Word(text="1023", box=[0, 20, 30, 30])]
    assert [w.text for w in merge_words(a, b)] == ["FT", "1023"]


def test_region_ocr_rereads_symbols_with_missing_tag_parts(pages) -> None:
    """On an OCR'd page where the bubble letters were missed, the symbol is re-read on its own."""
    from workbench_core.symbols.ocr import join_split_letters

    tis, lib = _starter()
    p1 = pages[0]
    gray = decode_gray(p1.png)
    letters = {w.text for w in p1.words if w.text.isalpha() and len(w.text) <= 3}
    page_words = [w for w in p1.words if w.text not in letters]  # what Windows OCR gave: no FT/PT/...
    calls = []

    def region(g, box):
        calls.append(box)
        return [w for w in p1.words if w.text in letters and box[0] <= w.box[0] and w.box[2] <= box[2]
                and box[1] <= w.box[1] and w.box[3] <= box[3]]

    without = analyse_page(1, gray, page_words, "ocr", tis, {}, lib)
    assert "FT-1023" not in {t.tag for t in without.tags}
    res = analyse_page(1, gray, page_words, "ocr", tis, {}, lib, region)
    tags = {t.tag for t in res.tags}
    assert {"FT-1023", "PT-1025", "FV-1023", "TT-1026A", "PI-1041"} <= tags
    assert len(calls) == 7  # every bubble on sheet 1 lost its letters in this fake OCR
    # Not used on PDF text, nor when every tag point was found.
    calls.clear()
    analyse_page(1, gray, p1.words, "pdf", tis, {}, lib, region)
    analyse_page(1, gray, p1.words, "ocr", tis, {}, lib, region)
    assert calls == []

    split = [Word(text="F", box=[10, 10, 16, 22]), Word(text="T", box=[17, 10, 23, 22]), Word(text="1023", box=[8, 26, 30, 38])]
    assert [w.text for w in join_split_letters(split)] == ["FT", "1023"]


def test_apply_review_matches_by_overlap_and_is_repeatable() -> None:
    from workbench_core.symbols import PageResult, PageReview, Rejection, Symbol, Word, apply_review
    lib = Library(id="l", name="L", tag_pattern=r"(?P<f>[A-Z]{2,3})-(?P<n>\d{3,4})", pattern_scan=True)
    t = Template(id="t", library_id="l", desc="Bubble", width=100, height=100)
    a = Symbol(template_id="t", template_desc="Bubble", box=[0, 0, 100, 100], score=0.9, tag="FT-101")
    b = Symbol(template_id="t", template_desc="Bubble", box=[300, 0, 400, 100], score=0.9, tag="PT-102")
    words = [Word(text="FT-101", box=[30, 40, 70, 60]), Word(text="LT-500", box=[600, 10, 650, 20])]
    res = PageResult(page=1, symbols=[a, b])
    review = PageReview(rejected=[Rejection(kind="symbol", box=[4, 3, 104, 103], template_id="t"),
                                  Rejection(kind="tag", box=[598, 8, 652, 22], tag="LT-500")],
                        added=[Symbol(template_id="t", template_desc="", box=[800, 0, 900, 100], score=0.4,
                                      origin="manual", tag_override="TT-900")])
    out = apply_review(res, words, review, lib, {"t": t})
    assert [s.tag for s in out.symbols] == ["PT-102", "TT-900"]
    assert [s.tag for s in out.rejected_symbols] == ["FT-101"]
    assert [x.tag for x in out.rejected_tags] == ["LT-500"]
    assert sorted(x.tag for x in out.tags) == ["PT-102", "TT-900"]  # FT-101's own text isn't re-found
    again = apply_review(out, words, review, lib, {"t": t})
    assert again.model_dump() == out.model_dump()
    restored = apply_review(out, words, PageReview(), lib, {"t": t})
    assert sorted(x.tag for x in restored.tags) == ["FT-101", "LT-500", "PT-102"]


def test_trim_box_matches_trim() -> None:
    from workbench_core.symbols.templates import crop, trim, trim_box
    page = np.full((200, 300), 255, np.uint8)
    cv2.circle(page, (150, 100), 20, 0, 2)
    box = trim_box(page, [100, 50, 220, 160])
    assert box == [127.0, 77.0, 174.0, 124.0]
    assert crop(page, box).shape == trim(crop(page, [100, 50, 220, 160])).shape
    with pytest.raises(ValueError, match="no linework"):
        trim_box(page, [0, 0, 50, 50])


def test_the_text_scan_is_off_in_a_new_library() -> None:
    assert Library(id="n", name="New", tag_pattern=r"[A-Z]+-\d+").pattern_scan is False
    assert STARTER_LIBRARY["library"]["pattern_scan"] is False
    words = [Word(text="FT-1023", box=[0, 0, 40, 12])]
    assert pattern_scan(words, TagRules(Library(id="n", name="New", tag_pattern=r"[A-Z]+-\d+"))) == []
