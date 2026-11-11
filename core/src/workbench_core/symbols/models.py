# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Symbol detection data shapes. Every box is [x1, y1, x2, y2] in rendered-image pixels
(200 DPI, page rotation applied), so symbols, words and tag points share one frame.

Nothing here is specific to P&IDs: a *library* holds the symbol templates for one kind of
drawing, plus how its text tags look (a regular expression and an output format). The
app ships with a P&ID instrument library as a ready-made example."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

DPI = 200
Box = list[float]
TextSource = Literal["pdf", "ocr", "none"]
MaskMode = Literal["auto", "custom", "none"]


class Word(BaseModel):
    text: str
    box: Box
    block: int = 0
    line: int = 0
    word_no: int = 0


class Exclusion(BaseModel):
    """Text to ignore: words (exact, case-insensitive) and page areas given as fractions
    of the page (so one title-block box fits every sheet of the same layout)."""
    words: list[str] = Field(default_factory=list)
    areas: list[Box] = Field(default_factory=list)  # [fx1, fy1, fx2, fy2] in 0..1


class Library(BaseModel):
    """Templates and tag rules for one kind of drawing."""
    id: str
    name: str
    description: str = ""
    # A text tag. Named groups ((?P<name>...)) become columns of the tags list. Blank:
    # template tags are taken as written and there is no text scan.
    tag_pattern: str = ""
    # How a tag is written in the output, from the pattern's groups, e.g. "{function}-{loop}".
    # Blank: the text as found.
    tag_format: str = ""
    pattern_scan: bool = False   # also find tags anywhere in the page text (off unless switched on)
    scan_stacked: bool = True    # ... including two words stacked one above the other
    min_pdf_words: int = 5       # fewer words than this in the PDF text -> OCR the page
    default_threshold: float = 0.8
    exclusion: Exclusion = Field(default_factory=Exclusion)
    created_at: datetime | None = None


class PageInfo(BaseModel):
    n: int  # 1-based
    width_px: int
    height_px: int
    rotation: int = 0
    text_source: TextSource = "pdf"
    word_count: int = 0
    warnings: list[str] = Field(default_factory=list)


class Drawing(BaseModel):
    id: str
    file_name: str
    library_id: str
    force_ocr: bool = False
    pages: list[PageInfo] = Field(default_factory=list)
    status: Literal["rendering", "ready", "error"] = "rendering"
    error: str | None = None
    uploaded_at: datetime | None = None


class TagPoint(BaseModel):
    """'The text at this point inside the symbol is this part of its tag' (PRD 5.5).
    x, y are pixels from the template's top-left corner."""
    name: str
    x: float
    y: float
    min_overlap: float = 0.5


class Variants(BaseModel):
    rot90: bool = False
    rot180: bool = False
    rot270: bool = False
    mirror: bool = False


class Template(BaseModel):
    """A symbol image searched for on every page of drawings that use its library."""
    id: str
    library_id: str
    desc: str = "Symbol"
    priority: int = 0  # lower runs first; each match is blanked before the next template
    active: bool = True
    threshold: float = 0.8
    # Which pixels are scored: "auto" = the symbol's lines widened by buffer_space, so
    # pipes or text crossing it don't count; "custom" = a mask painted or uploaded by the
    # user; "none" = the whole rectangle.
    mask_mode: MaskMode = "auto"
    buffer_space: int = 2
    variants: Variants = Field(default_factory=Variants)
    scales: list[float] = Field(default_factory=lambda: [1.0])
    max_hits: int = 1000
    tag_format: str = ""  # e.g. "{Function}-{Number}"; blank joins the parts with '-'
    points: list[TagPoint] = Field(default_factory=list)
    width: int = 0
    height: int = 0
    has_custom_mask: bool = False


class PageOverride(BaseModel):
    """Per-page threshold override, or skip the template on that page (PRD FR-7)."""
    template_id: str
    threshold: float | None = None
    ignore: bool = False


class Symbol(BaseModel):
    template_id: str
    template_desc: str
    box: Box
    score: float
    variant: str = "0"
    parts: dict[str, str | None] = Field(default_factory=dict)
    tag: str | None = None
    origin: Literal["auto", "manual"] = "auto"  # manual: added by the user on review
    tag_override: str | None = None  # manual symbols: tag typed by the user


class FoundTag(BaseModel):
    tag: str
    groups: dict[str, str] = Field(default_factory=dict)  # the library pattern's named groups
    source: Literal["template", "pattern"] = "pattern"
    template_desc: str = ""
    box: Box
    page: int = 0


class SkippedTemplate(BaseModel):
    template_id: str
    desc: str
    hits: int
    reason: str


class Rejection(BaseModel):
    """A detection the user marked as a false positive. Matched to later detections by box."""
    kind: Literal["symbol", "tag"]
    box: Box
    template_id: str | None = None  # symbols
    tag: str | None = None  # text-scan tags


class PageReview(BaseModel):
    """The user's corrections to one drawing page, re-applied on every analysis."""
    rejected: list[Rejection] = Field(default_factory=list)
    added: list[Symbol] = Field(default_factory=list)


class PageResult(BaseModel):
    page: int
    text_source: TextSource = "pdf"
    symbols: list[Symbol] = Field(default_factory=list)
    tags: list[FoundTag] = Field(default_factory=list)
    skipped: list[SkippedTemplate] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    rejected_symbols: list[Symbol] = Field(default_factory=list)  # left out of tags; shown for undo
    rejected_tags: list[FoundTag] = Field(default_factory=list)


class RunInfo(BaseModel):
    id: str
    doc_ids: list[str]
    columns: list[str] = Field(default_factory=list)  # tag-pattern groups shown as columns
    status: Literal["queued", "running", "done", "cancelled", "error"] = "queued"
    done_steps: int = 0
    total_steps: int = 0
    current: str = ""
    started_at: datetime | None = None
    finished_at: datetime | None = None
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    tag_count: int = 0
