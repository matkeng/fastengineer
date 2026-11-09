"""One page end to end, and the tags list across drawings."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .match import TemplateImage, locate_symbols
from .models import Library, PageOverride, PageResult, TextSource, Word
from .ocr import OcrProvider
from .tags import TagRules, apply_exclusion, format_tag, pattern_scan, resolve_points, symbol_tags
from .templates import erase_words

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


def analyse_page(page: int, gray, words: list[Word], text_source: TextSource, templates: list[TemplateImage],
                 overrides: dict[str, PageOverride], lib: Library) -> PageResult:
    rules = TagRules(lib)
    h, w = gray.shape[:2]
    words = apply_exclusion(words, lib.exclusion, w, h)
    matched = locate_symbols(erase_words(gray, words), templates, overrides)
    by_id = {t.template.id: t.template for t in templates}
    for s in matched.symbols:
        t = by_id[s.template_id]
        s.parts = resolve_points(s, t, words)
        s.tag = format_tag(t, s.parts)
    tags = symbol_tags(matched.symbols, pattern_scan(words, rules, page), rules, page)
    warnings = [f"Template '{s.desc}' skipped: {s.reason}" for s in matched.skipped]
    return PageResult(page=page, text_source=text_source, symbols=matched.symbols, tags=tags,
                      skipped=matched.skipped, warnings=warnings)


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
