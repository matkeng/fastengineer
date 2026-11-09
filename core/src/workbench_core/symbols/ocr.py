# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""OCR for pages without a text layer (scans, outlined text).

The production engine is Windows' built-in OCR (Windows.Media.Ocr via pywinrt), so
nothing is bundled. Anything with `read(gray_image) -> list[Word]` works as a provider,
which is how the tests exercise the fallback on Linux."""

from __future__ import annotations

import asyncio
import sys
from typing import Protocol

from .models import Word


class OcrProvider(Protocol):
    name: str

    def read(self, gray) -> list[Word]: ...


class OcrUnavailable(RuntimeError):
    pass


TILE = 3000     # px; Windows OCR reads small text better on moderate tiles
OVERLAP = 200   # px; words are kept by the tile whose core holds their centre


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
        import cv2
        try:  # WinRT needs COM on this thread; harmless if it's already initialised
            from winrt import _winrt
            _winrt.init_apartment(_winrt.MTA)
        except Exception:
            pass
        tile = min(TILE, self._max)
        h, w = gray.shape[:2]

        async def run_all():
            words: list[Word] = []
            for i, (x0, y0, x1, y1, (cx0, cy0, cx1, cy1)) in enumerate(_tiles(h, w, tile)):
                ok, buf = cv2.imencode(".png", cv2.cvtColor(gray[y0:y1, x0:x1], cv2.COLOR_GRAY2BGR))
                for j, (text, x, y, ww, hh) in enumerate(await self._read_tile(buf.tobytes())):
                    box = [x0 + x, y0 + y, x0 + x + ww, y0 + y + hh]
                    mx, my = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
                    if cx0 <= mx < cx1 and cy0 <= my < cy1:
                        words.append(Word(text=text, box=[round(v, 1) for v in box], block=i, line=0, word_no=j))
            return words

        return asyncio.run(run_all())


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
