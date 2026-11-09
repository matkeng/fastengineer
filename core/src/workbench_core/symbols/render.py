# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Split a PDF into page renders and text-layer words, with PDFium (pypdfium2).

Renders are lossless greyscale PNGs at DPI with the page's /Rotate applied, and words are
mapped into the same pixel frame, so text boxes always line up with the image (PRD 11 #4,
#13). PDFium gives characters, which are grouped into words here: a word ends at
whitespace, a line break, or a gap wider than about half a character."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from dataclasses import dataclass

from .models import DPI, Word

# PDFium is not thread-safe; the engine renders on one worker, but be safe anyway.
_pdfium_lock = threading.RLock()


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


def _open(data: bytes):
    import pypdfium2 as pdfium
    try:
        return pdfium.PdfDocument(data)
    except pdfium.PdfiumError as exc:
        msg = str(exc)
        if "password" in msg.lower():
            raise PdfError("This PDF is password protected.") from exc
        raise PdfError(f"This file could not be read as a PDF ({msg}).") from exc


def page_count(data: bytes) -> int:
    with _pdfium_lock:
        pdf = _open(data)
        try:
            return len(pdf)
        finally:
            pdf.close()


def _to_pixels(rotation: int, crop: tuple[float, float, float, float], zoom: float):
    """Map PDF user space (origin bottom-left, unrotated) to image pixels (origin top-left,
    rotation applied)."""
    left, bottom, right, top = crop
    w, h = right - left, top - bottom

    def f(x: float, y: float) -> tuple[float, float]:
        u, v = x - left, top - y  # unrotated, top-left origin
        if rotation == 90:
            u, v = h - v, u
        elif rotation == 180:
            u, v = w - u, h - v
        elif rotation == 270:
            u, v = v, w - u
        return u * zoom, v * zoom
    return f


def _words(page, rotation: int, zoom: float, width_px: int, height_px: int) -> list[Word]:
    import pypdfium2.raw as c
    tp = page.get_textpage()
    try:
        n = tp.count_chars()
        if n <= 0:
            return []
        to_px = _to_pixels(rotation, page.get_cropbox(), zoom)
        words: list[Word] = []
        cur: list[tuple[str, list[float]]] = []
        line = 0

        def flush():
            if cur:
                text = "".join(ch for ch, _ in cur)
                x1 = max(min(b[0] for _, b in cur), 0)
                y1 = max(min(b[1] for _, b in cur), 0)
                x2 = min(max(b[2] for _, b in cur), width_px)
                y2 = min(max(b[3] for _, b in cur), height_px)
                if text.strip() and x2 > x1 and y2 > y1:
                    words.append(Word(text=text, box=[round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)],
                                      line=line, word_no=len(words)))
                cur.clear()

        for i in range(n):
            code = c.FPDFText_GetUnicode(tp.raw, i)
            ch = chr(code) if code else ""
            if not ch or ch.isspace() or c.FPDFText_IsGenerated(tp.raw, i) == 1 and ch in "\r\n ":
                if ch in "\r\n":
                    line += 1
                flush()
                continue
            l_, b_, r_, t_ = tp.get_charbox(i)
            (ax, ay), (bx, by) = to_px(l_, b_), to_px(r_, t_)
            box = [min(ax, bx), min(ay, by), max(ax, bx), max(ay, by)]
            if cur:
                last = cur[-1][1]
                hgt = max(box[3] - box[1], last[3] - last[1], 1.0)
                gap = box[0] - last[2]
                same_line = abs((box[1] + box[3]) / 2 - (last[1] + last[3]) / 2) < 0.6 * hgt
                if not same_line or gap > 0.5 * hgt or gap < -hgt:
                    flush()
            cur.append((ch, box))
        flush()
        return words
    finally:
        tp.close()


def render_pages(data: bytes, dpi: int = DPI) -> Iterator[RenderedPage]:
    zoom = dpi / 72
    with _pdfium_lock:
        pdf = _open(data)
        try:
            for i in range(len(pdf)):
                page = pdf[i]
                try:
                    rotation = page.get_rotation() % 360
                    bitmap = page.render(scale=zoom, grayscale=True)
                    img = bitmap.to_numpy()
                    if img.ndim == 3:
                        img = img[:, :, 0]
                    h, w = img.shape[:2]
                    words = _words(page, rotation, zoom, w, h)
                    png = encode_png(img)
                    bitmap.close()
                finally:
                    page.close()
                yield RenderedPage(n=i + 1, png=png, width_px=w, height_px=h, rotation=rotation, words=words)
        finally:
            pdf.close()


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
    import numpy as np
    ok, buf = cv2.imencode(".png", np.ascontiguousarray(img))
    if not ok:
        raise PdfError("Image could not be encoded.")
    return buf.tobytes()
