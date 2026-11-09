"""One page end to end, and the P&ID tags list across drawings."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .match import TemplateImage, locate_symbols
from .models import Exclusion, PageOverride, PageResult, Settings, TextSource, Word
from .ocr import OcrProvider
from .templates import erase_words
from .tags import apply_exclusion, compile_pattern, format_tag, pattern_scan, resolve_points, symbol_tags

TAG_HEADERS = ["Tag", "Function", "Loop", "Suffix", "Count", "Drawings", "Sheets", "Templates", "Source"]


def choose_words(gray, pdf_words: list[Word], settings: Settings, force_ocr: bool,
                 ocr: Callable[[], tuple[OcrProvider | None, str | None]]) -> tuple[list[Word], TextSource, list[str]]:
    """PDF text layer first; OCR when the page has (almost) none or the drawing asks for it."""
    if not force_ocr and len(pdf_words) >= settings.min_pdf_words:
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


def analyse_page(page: int, gray, words: list[Word], text_source: TextSource, templates: list[TemplateImage],
                 overrides: dict[str, PageOverride], settings: Settings, exclusion: Exclusion | None) -> PageResult:
    rx = compile_pattern(settings.tag_pattern)
    h, w = gray.shape[:2]
    words = apply_exclusion(words, exclusion, w, h)
    matched = locate_symbols(erase_words(gray, words), templates, overrides)
    by_id = {t.template.id: t.template for t in templates}
    for s in matched.symbols:
        t = by_id[s.template_id]
        s.parts = resolve_points(s, t, words)
        s.tag = format_tag(t, s.parts)
    pattern = pattern_scan(words, rx, page) if settings.pattern_scan else []
    tags = symbol_tags(matched.symbols, pattern, rx, page)
    warnings = [f"Template '{s.desc}' skipped: {s.reason}" for s in matched.skipped]
    return PageResult(page=page, text_source=text_source, symbols=matched.symbols, tags=tags,
                      skipped=matched.skipped, warnings=warnings)


@dataclass
class SheetResult:
    file_name: str
    result: PageResult


def tags_table(sheets: list[SheetResult]) -> tuple[list[str], list[dict[str, str]]]:
    """One row per unique tag; repeats across sheets are counted and listed."""
    agg: dict[str, dict] = {}
    for sh in sheets:
        for t in sh.result.tags:
            a = agg.setdefault(t.tag, {"t": t, "count": 0, "drawings": [], "sheets": [], "templates": [], "src": set()})
            a["count"] += 1
            for k, v in (("drawings", sh.file_name), ("sheets", f"{sh.file_name} p{sh.result.page}"),
                         ("templates", t.template_desc)):
                if v and v not in a[k]:
                    a[k].append(v)
            a["src"].add(t.source)
    rows = []
    for tag in sorted(agg):
        a = agg[tag]
        t = a["t"]
        rows.append({"Tag": tag, "Function": t.function, "Loop": t.loop, "Suffix": t.suffix,
                     "Count": str(a["count"]), "Drawings": "; ".join(a["drawings"]),
                     "Sheets": "; ".join(a["sheets"]), "Templates": "; ".join(a["templates"]),
                     "Source": "template" if "template" in a["src"] else "pattern"})
    return TAG_HEADERS, rows
