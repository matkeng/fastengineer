"""P&ID analysis data shapes. Every box is [x1, y1, x2, y2] in rendered-image pixels
(200 DPI, page rotation applied), so symbols, words and tag points share one frame."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

DPI = 200
Box = list[float]
TextSource = Literal["pdf", "ocr", "none"]


class Word(BaseModel):
    text: str
    box: Box
    block: int = 0
    line: int = 0
    word_no: int = 0


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
    drawing_type: str = "PID"
    block_set: str = "FIR"
    force_ocr: bool = False
    pages: list[PageInfo] = Field(default_factory=list)
    status: Literal["rendering", "ready", "error"] = "rendering"
    error: str | None = None
    uploaded_at: datetime | None = None


class TagPoint(BaseModel):
    """'The text at this point inside the symbol is this tag part' (PRD 5.5).
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
    """A block template: a symbol image searched for on every page of its library."""
    id: str
    desc: str = "Symbol"
    drawing_type: str = "PID"
    block_set: str = "FIR"
    priority: int = 0  # lower runs first; each match is whited out before the next template
    active: bool = True
    threshold: float = 0.8
    buffer_space: int = 2
    use_mask: bool = True
    variants: Variants = Field(default_factory=Variants)
    scales: list[float] = Field(default_factory=lambda: [1.0])
    max_hits: int = 1000
    tag_format: str = ""  # e.g. "{Function}-{Number}"; blank joins the parts with '-'
    points: list[TagPoint] = Field(default_factory=list)
    width: int = 0
    height: int = 0


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


class FoundTag(BaseModel):
    tag: str
    function: str = ""
    loop: str = ""
    suffix: str = ""
    source: Literal["template", "pattern"] = "pattern"
    template_desc: str = ""
    box: Box
    page: int = 0


class SkippedTemplate(BaseModel):
    template_id: str
    desc: str
    hits: int
    reason: str


class PageResult(BaseModel):
    page: int
    text_source: TextSource = "pdf"
    symbols: list[Symbol] = Field(default_factory=list)
    tags: list[FoundTag] = Field(default_factory=list)
    skipped: list[SkippedTemplate] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class Exclusion(BaseModel):
    """Text to ignore for a library: words (exact, case-insensitive) and page areas
    given as fractions of the page (so one title-block box fits every sheet)."""
    words: list[str] = Field(default_factory=list)
    areas: list[Box] = Field(default_factory=list)  # [fx1, fy1, fx2, fy2] in 0..1


class Settings(BaseModel):
    tag_pattern: str = r"^(?P<function>[A-Z]{1,5})[- ]?(?P<loop>\d{2,6})(?P<suffix>[A-Z]{0,2})$"
    pattern_scan: bool = True
    min_pdf_words: int = 5  # fewer words than this on a page -> OCR it
    exclusions: dict[str, Exclusion] = Field(default_factory=dict)  # key "TYPE/SET"


class RunInfo(BaseModel):
    id: str
    doc_ids: list[str]
    status: Literal["queued", "running", "done", "cancelled", "error"] = "queued"
    done_steps: int = 0
    total_steps: int = 0
    current: str = ""
    started_at: datetime | None = None
    finished_at: datetime | None = None
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None
    tag_count: int = 0
