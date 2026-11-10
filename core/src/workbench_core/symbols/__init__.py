# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Symbol detection: find any symbol on PDF drawings with OpenCV template matching and
read the text tag written in or beside it (PDF text layer, or Windows OCR on scans).

Templates and tag rules live in *libraries*; the app ships with a P&ID instrument library
(see starter.py). OpenCV, NumPy and PDFium are imported inside functions, so importing
this package is cheap."""

from .models import (
    DPI,
    Drawing,
    Exclusion,
    FoundTag,
    Library,
    PageInfo,
    PageOverride,
    PageResult,
    PageReview,
    Rejection,
    RunInfo,
    SkippedTemplate,
    Symbol,
    TagPoint,
    Template,
    Variants,
    Word,
)
from .pipeline import FIXED_HEADERS, SheetResult, analyse_page, apply_review, choose_words, tags_table

__all__ = [
    "DPI", "Drawing", "Exclusion", "FoundTag", "Library", "PageInfo", "PageOverride", "PageResult", "PageReview", "Rejection", "RunInfo",
    "SkippedTemplate", "Symbol", "TagPoint", "Template", "Variants", "Word",
    "FIXED_HEADERS", "SheetResult", "analyse_page", "apply_review", "choose_words", "tags_table",
]
