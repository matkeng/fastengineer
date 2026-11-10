# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""One page end to end, and the tags list across drawings."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .match import TemplateImage, _iou, locate_symbols
from .models import Box, FoundTag, Library, PageOverride, PageResult, PageReview, Rejection, Symbol, Template, TextSource, Word
from .ocr import OcrProvider, merge_words
from .tags import TagRules, apply_exclusion, format_tag, pattern_scan, resolve_points, symbol_tags
from .templates import erase_words

REVIEW_IOU = 0.5  # a rejection matches a detection whose box overlaps it this much
FIXED_HEADERS = ["Count", "Drawings", "Sheets", "Symbols", "Source"]


def choose_words(gray, pdf_words: list[Word], lib: Library, force_ocr: bool,
                 ocr: Callable[[], tuple[OcrProvider | None, str | None]]) -> tuple[list[Word], TextSource, list[str]]:
    """PDF text layer first; OCR when the page has (almost) none or the drawing asks for it."""
    if not force_ocr and len(pdf_words) >= lib.min_pdf_words:
        return pdf_words, "pdf", []
    provider, why = ocr()
    if provider is None:
        if pdf_words:
            return pdf_words, "pdf", [f"Only {len(pdf_words)} word(s) in the text layer and OCR is unavailable: {why}"]
        return [], "none", [f"No text layer and OCR is unavailable: {why}"]
    try:
        words = provider.read(gray)
    except Exception as exc:  # OCR failures shouldn't lose the symbols
        return pdf_words, "pdf" if pdf_words else "none", [f"{provider.name} failed on this page: {exc}"]
    return words, "ocr", []


RegionOcr = Callable[[object, list[float]], list[Word]]


def _read_symbol(s: Symbol, t: Template, words: list[Word], gray, text_source: TextSource,
                 region_ocr: RegionOcr | None) -> list[Word]:
    """Fill a symbol's tag parts and tag from the words; returns the words (plus any read
    again from the symbol's own region)."""
    s.parts = resolve_points(s, t, words)
    if region_ocr is not None and gray is not None and text_source == "ocr" and any(v is None for v in s.parts.values()):
        extra = region_ocr(gray, s.box)
        if extra:
            s.parts = resolve_points(s, t, merge_words(extra, words))
            words = merge_words(words, extra)
    s.tag = s.tag_override or format_tag(t, s.parts)
    return words


def _centre_in(a: Box, b: Box) -> bool:
    cx, cy = (a[0] + a[2]) / 2, (a[1] + a[3]) / 2
    return b[0] <= cx <= b[2] and b[1] <= cy <= b[3]


def rejects_symbol(r: Rejection, s: Symbol) -> bool:
    return r.kind == "symbol" and (r.template_id in (None, s.template_id)) and _iou(r.box, s.box) >= REVIEW_IOU


def rejects_tag(r: Rejection, t: FoundTag) -> bool:
    return r.kind == "tag" and (_iou(r.box, t.box) >= REVIEW_IOU or (r.tag == t.tag and _centre_in(t.box, r.box)))


def apply_review(res: PageResult, words: list[Word], review: PageReview | None, lib: Library,
                 templates: dict[str, Template], gray=None, region_ocr: RegionOcr | None = None) -> PageResult:
    """Apply the user's corrections to a page result: rejected detections move to
    rejected_symbols / rejected_tags, hand-added symbols are read and appended, and the tags
    are rebuilt. Matched symbols keep the parts they were read with, so this is cheap
    enough to run on every click and safe to run again on its own output."""
    review = review or PageReview()
    rules = TagRules(lib)
    h, w = (gray.shape[:2] if gray is not None else (0, 0))
    if gray is not None:
        words = apply_exclusion(words, lib.exclusion, w, h)
    auto = [s for s in [*res.symbols, *res.rejected_symbols] if s.origin == "auto"]
    keep: list[Symbol] = []
    gone: list[Symbol] = []
    for s in auto:
        (gone if any(rejects_symbol(r, s) for r in review.rejected) else keep).append(s)
    for a in review.added:
        s = a.model_copy(deep=True)
        t = templates.get(s.template_id)
        if t is not None:
            s.template_desc = t.desc
            words = _read_symbol(s, t, words, gray, res.text_source, region_ocr)
        else:
            s.tag = s.tag_override or s.tag
        keep.append(s)
    # Text inside a rejected symbol isn't a tag either (it was that symbol's tag).
    pattern = [p for p in pattern_scan(words, rules, res.page) if not any(_centre_in(p.box, g.box) for g in gone)]
    pattern_kept = [p for p in pattern if not any(rejects_tag(r, p) for r in review.rejected)]
    tags = symbol_tags(keep, pattern_kept, rules, res.page)
    rejected_tags = [p for p in pattern if p not in pattern_kept]
    return res.model_copy(update={"symbols": keep, "rejected_symbols": gone, "tags": tags,
                                  "rejected_tags": rejected_tags})


def analyse_page(page: int, gray, words: list[Word], text_source: TextSource, templates: list[TemplateImage],
                 overrides: dict[str, PageOverride], lib: Library,
                 region_ocr: RegionOcr | None = None, review: PageReview | None = None) -> PageResult:
    """region_ocr: on OCR'd pages, re-read a matched symbol on its own when some of its tag
    points found no text (small codes next to linework are what page-level OCR misses).
    review: the user's corrections to this page (false positives, symbols added by hand)."""
    rules = TagRules(lib)
    h, w = gray.shape[:2]
    words = apply_exclusion(words, lib.exclusion, w, h)
    matched = locate_symbols(erase_words(gray, words), templates, overrides)
    by_id = {t.template.id: t.template for t in templates}
    for s in matched.symbols:
        words = _read_symbol(s, by_id[s.template_id], words, gray, text_source, region_ocr)
    warnings = [f"Template '{s.desc}' skipped: {s.reason}" for s in matched.skipped]
    res = PageResult(page=page, text_source=text_source, symbols=matched.symbols, skipped=matched.skipped,
                     warnings=warnings)
    if review is not None and (review.rejected or review.added):
        return apply_review(res, words, review, lib, by_id, gray, region_ocr)
    res.tags = symbol_tags(matched.symbols, pattern_scan(words, rules, page), rules, page)
    return res


@dataclass
class SheetResult:
    file_name: str
    result: PageResult


def tags_table(sheets: list[SheetResult], columns: list[str] | None = None) -> tuple[list[str], list[dict[str, str]]]:
    """One row per unique tag; repeats across sheets are counted and listed. `columns` are
    the tag pattern's group names (e.g. function, loop), shown after the tag."""
    columns = [c for c in (columns or []) if c not in ("Tag", *FIXED_HEADERS)]
    agg: dict[str, dict] = {}
    for sh in sheets:
        for t in sh.result.tags:
            a = agg.setdefault(t.tag, {"groups": {}, "count": 0, "drawings": [], "sheets": [], "templates": [], "src": set()})
            for k, v in t.groups.items():
                if v and not a["groups"].get(k):
                    a["groups"][k] = v
            a["count"] += 1
            for k, v in (("drawings", sh.file_name), ("sheets", f"{sh.file_name} p{sh.result.page}"),
                         ("templates", t.template_desc)):
                if v and v not in a[k]:
                    a[k].append(v)
            a["src"].add(t.source)
    rows = []
    for tag in sorted(agg):
        a = agg[tag]
        row = {"Tag": tag, **{c: a["groups"].get(c, "") for c in columns}}
        row.update({"Count": str(a["count"]), "Drawings": "; ".join(a["drawings"]), "Sheets": "; ".join(a["sheets"]),
                    "Symbols": "; ".join(a["templates"]),
                    "Source": "template" if "template" in a["src"] else "text scan"})
        rows.append(row)
    return ["Tag", *columns, *FIXED_HEADERS], rows
