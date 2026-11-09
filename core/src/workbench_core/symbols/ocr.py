# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""OCR for pages without a text layer (scans, outlined text).

The production engine is Windows' built-in OCR (Windows.Media.Ocr via pywinrt), so
nothing is bundled. Anything with `read(gray_image) -> list[Word]` works as a provider,
which is how the tests exercise the fallback on Linux."""

from __future__ import annotations

import asyncio
import re
import sys
from typing import Protocol

from .models import Word


class OcrProvider(Protocol):
    name: str

    def read(self, gray) -> list[Word]: ...


class OcrUnavailable(RuntimeError):
    pass


TILE = 3000     # px (in the upscaled image); Windows OCR reads better on moderate tiles
OVERLAP = 300   # px (upscaled); words are kept by the tile whose core holds their centre
# OCR reads a text-only copy of the page (linework removed, see text_only) enlarged by this
# factor; word boxes are scaled back to page pixels.
OCR_SCALE = 2.0
MAX_CHAR_PX = 60   # at 200 DPI: characters up to ~20 pt; bubbles, pipes and symbols are larger

_PUNCT_ONLY = re.compile(r"^[\W_]+$")
_O_NEAR_DIGIT = re.compile(r"(?<=\d)[Oo]|[Oo](?=\d)")


def clean_ocr_text(text: str) -> str | None:
    """Fix common OCR confusions in codes; None for junk (punctuation only)."""
    t = text.strip().replace("|", "I")
    if not t or _PUNCT_ONLY.match(t):
        return None
    return _O_NEAR_DIGIT.sub("0", t)


def upscale(gray, scale: float = OCR_SCALE):
    """Enlarge a page for OCR, keeping line art crisp."""
    import cv2
    if scale == 1:
        return gray
    big = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    return cv2.normalize(big, None, 0, 255, cv2.NORM_MINMAX)


def text_only(gray, max_char_px: int = MAX_CHAR_PX, min_char_px: int = 4):
    """The page with only character-sized ink kept (black on white). Drawing linework
    (circles, pipes, leaders, symbol bodies) is larger, longer or mostly empty inside its
    bounding box, and confuses OCR's text-line finder."""
    import cv2
    import numpy as np
    _, ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    keep = np.zeros(n, bool)
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if w > max_char_px or h > max_char_px or area < 3:
            continue
        if h < min_char_px and w < min_char_px:  # specks (but keep '.' and '-' via area)
            if area < 3:
                continue
        if max(w, h) > 25 and area / float(w * h) < 0.15:  # thin arc or line fragment
            continue
        keep[i] = True
    out = np.full(gray.shape, 255, np.uint8)
    out[keep[labels]] = 0
    return out


def _iou(a: list[float], b: list[float]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def merge_words(primary: list[Word], extra: list[Word], iou: float = 0.3) -> list[Word]:
    """primary plus the extra words that don't overlap any of them."""
    out = list(primary)
    for w in extra:
        if all(_iou(w.box, p.box) < iou for p in primary):
            out.append(w)
    return out


async def ocr_page(gray, read_tile, tile: int = TILE) -> list[Word]:
    """Two passes: the text-only page enlarged (finds small codes next to linework), then the
    plain page at 1x for any text the first pass removed (e.g. touching a line)."""
    first = await ocr_tiles(text_only(gray), read_tile, tile, OCR_SCALE)
    second = await ocr_tiles(gray, read_tile, tile, 1.0)
    return merge_words(first, second)


async def ocr_tiles(gray, read_tile, tile: int = TILE, scale: float = OCR_SCALE) -> list[Word]:
    """Upscale, OCR tile by tile with `read_tile(png) -> [(text, x, y, w, h)]` (coroutine, in the
    tile's pixels), and return words in the original page's pixels."""
    import cv2
    big = upscale(gray, scale)
    h, w = big.shape[:2]
    words: list[Word] = []
    for i, (x0, y0, x1, y1, (cx0, cy0, cx1, cy1)) in enumerate(_tiles(h, w, tile, min(OVERLAP, tile // 4))):
        ok, buf = cv2.imencode(".png", cv2.cvtColor(big[y0:y1, x0:x1], cv2.COLOR_GRAY2BGR))
        for j, (text, x, y, ww, hh) in enumerate(await read_tile(buf.tobytes())):
            t = clean_ocr_text(text)
            if t is None:
                continue
            bx = [x0 + x, y0 + y, x0 + x + ww, y0 + y + hh]
            mx, my = (bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2
            if cx0 <= mx < cx1 and cy0 <= my < cy1:
                words.append(Word(text=t, box=[round(v / scale, 1) for v in bx], block=i, line=0, word_no=j))
    return words


def _tiles(h: int, w: int, tile: int = TILE, overlap: int = OVERLAP):
    """(x0, y0, x1, y1, core) windows covering the image; core is the region each tile owns."""
    step = tile - overlap
    xs = list(range(0, max(w - overlap, 1), step)) or [0]
    ys = list(range(0, max(h - overlap, 1), step)) or [0]
    for y0 in ys:
        for x0 in xs:
            x1, y1 = min(x0 + tile, w), min(y0 + tile, h)
            core = (0 if x0 == 0 else x0 + overlap / 2, 0 if y0 == 0 else y0 + overlap / 2,
                    w if x1 == w else x1 - overlap / 2, h if y1 == h else y1 - overlap / 2)
            yield x0, y0, x1, y1, core


class WindowsOcr:
    name = "Windows OCR"

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise OcrUnavailable("Windows OCR is only available on Windows.")
        try:
            from winrt.windows.media.ocr import OcrEngine
        except Exception as exc:  # missing package or WinRT not present
            raise OcrUnavailable(f"Windows OCR could not be loaded ({exc}).") from exc
        engine = OcrEngine.try_create_from_user_profile_languages()
        if engine is None:
            raise OcrUnavailable("Windows OCR has no language installed for this user "
                                 "(Settings > Time & language > Language: add an OCR-capable language).")
        self._engine = engine
        try:
            self._max = int(OcrEngine.max_image_dimension)
        except Exception:
            self._max = TILE

    async def _read_tile(self, png: bytes):
        from winrt.windows.graphics.imaging import BitmapDecoder, BitmapPixelFormat, SoftwareBitmap
        from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream
        stream = InMemoryRandomAccessStream()
        writer = DataWriter(stream)
        writer.write_bytes(png)
        await writer.store_async()
        await writer.flush_async()
        writer.detach_stream()
        stream.seek(0)
        decoder = await BitmapDecoder.create_async(stream)
        bmp = await decoder.get_software_bitmap_async()
        if bmp.bitmap_pixel_format != BitmapPixelFormat.BGRA8:
            bmp = SoftwareBitmap.convert(bmp, BitmapPixelFormat.BGRA8)
        result = await self._engine.recognize_async(bmp)
        out = []
        for line in result.lines:
            for w in line.words:
                r = w.bounding_rect
                out.append((w.text, r.x, r.y, r.width, r.height))
        return out

    def read(self, gray) -> list[Word]:
        try:  # WinRT needs COM on this thread; harmless if it's already initialised
            from winrt import _winrt
            _winrt.init_apartment(_winrt.MTA)
        except Exception:
            pass
        return asyncio.run(ocr_page(gray, self._read_tile, min(TILE, self._max)))


_cached: OcrProvider | None = None
_reason: str | None = None


def default_provider() -> tuple[OcrProvider | None, str | None]:
    """The platform OCR engine, or (None, why not)."""
    global _cached, _reason
    if _cached is None and _reason is None:
        try:
            _cached = WindowsOcr()
        except OcrUnavailable as exc:
            _reason = str(exc)
    return _cached, _reason
