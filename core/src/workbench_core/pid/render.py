"""Split a PDF into page renders and text-layer words (PyMuPDF).

Renders are lossless greyscale PNGs at DPI with the page's /Rotate applied, and words
are mapped into the same pixel frame with the page's rotation matrix, so text boxes
always line up with the image (PRD 11 #4, #13)."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from .models import DPI, Word


class PdfError(ValueError):
    pass


@dataclass
class RenderedPage:
    n: int
    png: bytes
    width_px: int
    height_px: int
    rotation: int
    words: list[Word]


def page_count(data: bytes) -> int:
    import fitz
    try:
        with fitz.open(stream=data, filetype="pdf") as doc:
            return doc.page_count
    except Exception as exc:  # fitz raises its own types
        raise PdfError(f"This file could not be read as a PDF ({exc}).") from exc


def render_pages(data: bytes, dpi: int = DPI) -> Iterator[RenderedPage]:
    import fitz
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise PdfError(f"This file could not be read as a PDF ({exc}).") from exc
    if doc.needs_pass:
        raise PdfError("This PDF is password protected.")
    zoom = dpi / 72
    with doc:
        for page in doc:
            pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY, alpha=False)
            to_px = page.rotation_matrix * fitz.Matrix(zoom, zoom)
            words = []
            for x0, y0, x1, y1, text, block, line, word_no in page.get_text("words"):
                r = (fitz.Rect(x0, y0, x1, y1) * to_px) & fitz.Rect(0, 0, pix.width, pix.height)  # normalised, clipped
                if r.is_empty or not text.strip():
                    continue
                words.append(Word(text=text, box=[round(r.x0, 1), round(r.y0, 1), round(r.x1, 1), round(r.y1, 1)],
                                  block=block, line=line, word_no=word_no))
            yield RenderedPage(n=page.number + 1, png=pix.tobytes("png"), width_px=pix.width,
                               height_px=pix.height, rotation=page.rotation, words=words)


def decode_gray(png: bytes):
    """PNG bytes -> uint8 greyscale array."""
    import cv2
    import numpy as np
    img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise PdfError("Image could not be decoded.")
    return img


def encode_png(img) -> bytes:
    import cv2
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise PdfError("Image could not be encoded.")
    return buf.tobytes()
