"""P&ID analysis: symbol templates matched with OpenCV, tags read from the PDF text
layer (or Windows OCR on scans), and a P&ID tags list that feeds the list import.

OpenCV, NumPy and PyMuPDF are imported inside functions, so importing this package is cheap."""

from .models import (
    DPI,
    Drawing,
    Exclusion,
    FoundTag,
    PageInfo,
    PageOverride,
    PageResult,
    RunInfo,
    Settings,
    SkippedTemplate,
    Symbol,
    TagPoint,
    Template,
    Variants,
    Word,
)
from .pipeline import TAG_HEADERS, SheetResult, analyse_page, choose_words, tags_table

__all__ = [
    "DPI", "Drawing", "Exclusion", "FoundTag", "PageInfo", "PageOverride", "PageResult", "RunInfo",
    "Settings", "SkippedTemplate", "Symbol", "TagPoint", "Template", "Variants", "Word",
    "TAG_HEADERS", "SheetResult", "analyse_page", "choose_words", "tags_table",
]
