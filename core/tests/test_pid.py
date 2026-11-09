from __future__ import annotations

import base64
import json
from pathlib import Path

import numpy as np
import pytest

fitz = pytest.importorskip("fitz")
cv2 = pytest.importorskip("cv2")

from workbench_core.pid import (  # noqa: E402
    Exclusion,
    PageOverride,
    Settings,
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
from workbench_core.pid.export import tags_csv, tags_xlsx  # noqa: E402
from workbench_core.pid.match import locate_symbols, nms, prepare  # noqa: E402
from workbench_core.pid.render import decode_gray, render_pages  # noqa: E402
from workbench_core.pid.tags import (  # noqa: E402
    apply_exclusion,
    box_overlap,
    compile_pattern,
    format_tag,
    pattern_scan,
    point_in_symbol,
    resolve_points,
)
from workbench_core.pid.templates import make_mask, trim  # noqa: E402

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
EXPECTED = {"FV-1023", "FV-1024", "FT-1023", "PT-1025", "TT-1026A", "LIC-1030", "PI-1041", "PSV-1040",
            "FT-2001", "PT-2002", "FV-2001"}


def _library():
    lib = json.loads((SAMPLES / "pid-templates.json").read_text())
    out = []
    for i, raw in enumerate(lib["templates"]):
        raw = dict(raw)
        g = decode_gray(base64.b64decode(raw.pop("image_png")))
        out.append(prepare(Template(id=f"t{i}", width=g.shape[1], height=g.shape[0], **raw), g))
    return out, Exclusion(**lib["exclusions"]["PID/FIR"])


@pytest.fixture(scope="module")
def pages():
    return list(render_pages((SAMPLES / "pid-sample.pdf").read_bytes()))


@pytest.fixture(scope="module")
def results(pages):
    lib, ex = _library()
    return [analyse_page(p.n, decode_gray(p.png), p.words, "pdf", lib, {}, Settings(), ex) for p in pages]


def test_render_puts_words_in_the_image_frame(pages) -> None:
    p1, p2 = pages
    assert (p1.width_px, p1.height_px, p1.rotation) == (3309, 2339, 0)
    assert (p2.width_px, p2.height_px, p2.rotation) == (2339, 3309, 90)  # /Rotate applied: portrait
    for p in pages:
        gray = decode_gray(p.png)
        assert gray.shape == (p.height_px, p.width_px)
        for w in p.words:
            x1, y1, x2, y2 = (int(v) for v in w.box)
            assert 0 <= x1 < x2 <= p.width_px and 0 <= y1 < y2 <= p.height_px
            assert (x2 - x1) > (y2 - y1) * 0.6 or len(w.text) <= 2  # upright text, also on the rotated sheet
            assert gray[y1:y2 + 1, x1:x2 + 1].min() < 128  # there is ink under every word box


def test_mask_is_the_widened_strokes() -> None:
    img = np.full((40, 40), 255, np.uint8)
    cv2.line(img, (5, 20), (35, 20), 0, 1)
    thin, wide = make_mask(img, 1), make_mask(img, 4)
    assert thin.sum() < wide.sum()
    assert (wide[:, 20] > 0).sum() > (thin[:, 20] > 0).sum() >= 1
    t = trim(img)
    assert t.shape[0] < 10 and t.shape[1] >= 30


def test_box_overlap_uses_the_smaller_box() -> None:
    assert box_overlap([0, 0, 100, 100], [10, 10, 20, 20]) == 1.0
    assert box_overlap([0, 0, 10, 10], [5, 0, 15, 10]) == 0.5
    assert box_overlap([0, 0, 10, 10], [20, 20, 30, 30]) == 0.0


def test_sample_finds_every_tag_with_templates(results) -> None:
    headers, rows = tags_table([SheetResult("pid-sample.pdf", r) for r in results])
    assert {r["Tag"] for r in rows} == EXPECTED
    ft = next(r for r in rows if r["Tag"] == "FT-1023")
    assert ft["Count"] == "2" and ft["Sheets"] == "pid-sample.pdf p1; pid-sample.pdf p2"
    assert ft["Source"] == "template" and ft["Templates"] == "Instrument bubble"
    tt = next(r for r in rows if r["Tag"] == "TT-1026A")
    assert (tt["Function"], tt["Loop"], tt["Suffix"]) == ("TT", "1026", "A")
    assert next(r for r in rows if r["Tag"] == "PSV-1040")["Source"] == "pattern"  # plain text, no symbol


def test_priority_whiteout_and_no_duplicates(results) -> None:
    p1 = results[0]
    kinds = [s.template_desc for s in p1.symbols]
    assert kinds.count("Instrument bubble") == 7
    assert kinds.count("Control valve") == 2
    assert kinds.count("Valve") == 2  # the control valves' bodies were erased before 'Valve' ran
    boxes = [s.box for s in p1.symbols]
    assert len(nms([(1.0, b, "0") for b in boxes])) == len(boxes)  # nothing overlaps


def test_title_block_text_is_excluded(pages, results) -> None:
    tags = {t.tag for r in results for t in r.tags}
    assert "PID-100" not in tags and "SHT-01" not in tags
    lib, _ = _library()
    p1 = pages[0]
    raw = analyse_page(1, decode_gray(p1.png), p1.words, "pdf", lib, {}, Settings(), None)
    assert {"PID-100", "SHT-01"} <= {t.tag for t in raw.tags}


def test_page_overrides_threshold_and_ignore(pages) -> None:
    lib, ex = _library()
    p1 = pages[0]
    gray = decode_gray(p1.png)
    bubble = lib[0].template.id
    ignored = analyse_page(1, gray, p1.words, "pdf", lib, {bubble: PageOverride(template_id=bubble, ignore=True)},
                           Settings(), ex)
    assert not any(s.template_desc == "Instrument bubble" for s in ignored.symbols)
    assert {t.tag for t in ignored.tags} >= {"FT-1023", "LIC-1030"}  # the pattern scan still reads them
    strict = analyse_page(1, gray, p1.words, "pdf", lib, {bubble: PageOverride(template_id=bubble, threshold=0.99)},
                          Settings(), ex)
    assert sum(s.template_desc == "Instrument bubble" for s in strict.symbols) == 1  # only the one it was cut from


def test_too_many_hits_is_reported_not_silent(pages) -> None:
    lib, ex = _library()
    lib[2].template.max_hits = 1
    p1 = pages[0]
    res = analyse_page(1, decode_gray(p1.png), p1.words, "pdf", lib, {}, Settings(), ex)
    assert [s.desc for s in res.skipped] == ["Valve"]
    assert "Valve" in res.warnings[0] and "raise the threshold" in res.warnings[0]


def test_downscale_guard_keeps_boxes_in_full_size_pixels(monkeypatch) -> None:
    from workbench_core.pid import match
    img = np.full((600, 800), 255, np.uint8)
    cv2.circle(img, (400, 300), 40, 0, 2)
    t = img[255:346, 355:446].copy()
    tmpl = prepare(Template(id="c", desc="circle", width=t.shape[1], height=t.shape[0]), t)
    full = locate_symbols(img, [tmpl]).symbols
    monkeypatch.setattr(match, "MAX_PIXELS", 120_000)  # forces scale 0.5
    scaled = locate_symbols(img, [tmpl]).symbols
    assert len(full) == len(scaled) == 1
    assert all(abs(a - b) <= 3 for a, b in zip(full[0].box, scaled[0].box)), (full[0].box, scaled[0].box)


def test_rotated_variant_and_tag_points_follow_rotation() -> None:
    t = Template(id="x", width=40, height=20, points=[TagPoint(name="P", x=30, y=5)])
    assert point_in_symbol(t, "0", 30, 5) == (30, 5)
    assert point_in_symbol(t, "90", 30, 5) == (15, 30)    # clockwise: x' = h - y, y' = x
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
    tpl = Template(id="a", desc="arrow", width=60, height=30, variants=Variants(rot90=True))
    syms = locate_symbols(img, [prepare(tpl, arrow)]).symbols
    assert sorted(s.variant for s in syms) == ["0", "90"]


def test_resolve_points_and_tag_format() -> None:
    t = Template(id="b", width=100, height=100, tag_format="{Function}-{Number}",
                 points=[TagPoint(name="Function", x=50, y=35), TagPoint(name="Number", x=50, y=65)])
    s = Symbol(template_id="b", template_desc="bubble", box=[1000, 1000, 1100, 1100], score=0.9)
    words = [Word(text="FT", box=[1040, 1028, 1060, 1042]), Word(text="1023", box=[1030, 1058, 1070, 1072]),
             Word(text="NOISE", box=[1095, 1030, 1200, 1040])]  # mostly outside: rejected by min_overlap
    parts = resolve_points(s, t, words)
    assert parts == {"Function": "FT", "Number": "1023"}
    assert format_tag(t, parts) == "FT-1023"
    assert format_tag(t, {"Function": "FT", "Number": None}) == "FT"
    assert format_tag(t, {"Function": None, "Number": None}) is None
    t2 = t.model_copy(update={"tag_format": ""})
    assert format_tag(t2, parts) == "FT-1023"


def test_pattern_scan_single_and_stacked() -> None:
    rx = compile_pattern(Settings().tag_pattern)
    words = [Word(text="PT", box=[100, 100, 120, 112]), Word(text="101A", box=[96, 116, 126, 128]),
             Word(text="FIC-2002.", box=[300, 100, 360, 112]), Word(text="1234", box=[500, 100, 530, 112]),
             Word(text="NOTE", box=[600, 100, 640, 112]), Word(text="12", box=[600, 116, 615, 128])]
    tags = {t.tag: t for t in pattern_scan(words, rx, 1)}
    assert set(tags) == {"PT-101A", "FIC-2002", "NOTE-12"}
    assert (tags["PT-101A"].function, tags["PT-101A"].loop, tags["PT-101A"].suffix) == ("PT", "101", "A")
    ex = Exclusion(words=["note"], areas=[])
    assert "NOTE-12" not in {t.tag for t in pattern_scan(apply_exclusion(words, ex, 1000, 1000), rx)}
    with pytest.raises(ValueError):
        compile_pattern(r"^[A-Z]+\d+$")


class FakeOcr:
    name = "Fake OCR"

    def __init__(self, words):
        self.words = words
        self.calls = 0

    def read(self, gray):
        self.calls += 1
        return self.words


def test_ocr_fallback_only_without_a_text_layer(pages) -> None:
    p1 = pages[0]
    gray = decode_gray(p1.png)
    fake = FakeOcr(p1.words)
    words, src, warn = choose_words(gray, p1.words, Settings(), False, lambda: (fake, None))
    assert (src, fake.calls, warn) == ("pdf", 0, [])
    words, src, warn = choose_words(gray, [], Settings(), False, lambda: (fake, None))
    assert (src, fake.calls, len(words)) == ("ocr", 1, len(p1.words))
    words, src, warn = choose_words(gray, p1.words, Settings(), True, lambda: (fake, None))  # forced
    assert src == "ocr"
    words, src, warn = choose_words(gray, [], Settings(), False, lambda: (None, "not on Windows"))
    assert src == "none" and "OCR is unavailable: not on Windows" in warn[0]


def test_scanned_sample_with_ocr_words_finds_the_tags(pages) -> None:
    """The image-only PDF has no words; with OCR words (here: the text layer's, standing in
    for Windows OCR) the same tags come out."""
    lib, ex = _library()
    scanned = list(render_pages((SAMPLES / "pid-sample-scanned.pdf").read_bytes()))
    assert all(not p.words for p in scanned)
    sheets = []
    for sp, tp in zip(scanned, pages):
        gray = decode_gray(sp.png)
        words, src, _ = choose_words(gray, sp.words, Settings(), False, lambda: (FakeOcr(tp.words), None))
        sheets.append(SheetResult("scan.pdf", analyse_page(sp.n, gray, words, src, lib, {}, Settings(), ex)))
    assert {r["Tag"] for r in tags_table(sheets)[1]} == EXPECTED


def test_exports(results) -> None:
    sheets = [SheetResult("pid-sample.pdf", r) for r in results]
    csv_text = tags_csv(sheets).decode("utf-8-sig")
    assert csv_text.splitlines()[0] == "Tag,Function,Loop,Suffix,Count,Drawings,Sheets,Templates,Source"
    from io import BytesIO

    from openpyxl import load_workbook
    wb = load_workbook(BytesIO(tags_xlsx(sheets, "test")))
    assert wb.sheetnames == ["P&ID tags", "Detections", "About"]
    assert wb["P&ID tags"].max_row == len(EXPECTED) + 1
