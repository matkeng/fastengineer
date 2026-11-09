"""Template images: crop from a page render, and the masks that say which pixels are scored."""

from __future__ import annotations

from .models import Box

INK = 160  # grey level below which a pixel counts as ink (renders are anti-aliased)


def ink(gray):
    """uint8 image: 255 where there is ink, 0 on paper. Page and template use the same rule."""
    import cv2
    _, out = cv2.threshold(gray, INK, 255, cv2.THRESH_BINARY_INV)
    return out


def make_mask(gray, buffer_space: int):
    """The template's strokes widened by (buffer_space - 1) dilations of a 2x2 kernel.
    Matching only scores this neighbourhood, so pipes or text crossing the symbol's
    box don't count against it."""
    import cv2
    import numpy as np
    m = ink(gray)
    n = max(int(buffer_space) - 1, 0)
    if n:
        m = cv2.dilate(m, np.ones((2, 2), np.uint8), iterations=n)
    return m


def erase_words(gray, words, pad: float = 0.5):
    """Paint the text boxes white. Symbols are matched (and templates cut) on this
    text-free image, so a bubble matches whatever tag is written in it."""
    out = gray.copy()
    h, w = out.shape[:2]
    for wd in words:
        x1, y1, x2, y2 = wd.box
        out[max(int(y1 - pad), 0):min(int(y2 + pad + 1), h), max(int(x1 - pad), 0):min(int(x2 + pad + 1), w)] = 255
    return out


def crop(gray, rect: Box):
    """Crop [x1, y1, x2, y2] (any corner order, clamped to the image)."""
    h, w = gray.shape[:2]
    x1, x2 = sorted((int(round(rect[0])), int(round(rect[2]))))
    y1, y2 = sorted((int(round(rect[1])), int(round(rect[3]))))
    x1, y1 = max(x1, 0), max(y1, 0)
    x2, y2 = min(x2, w), min(y2, h)
    if x2 - x1 < 4 or y2 - y1 < 4:
        raise ValueError("Draw a box at least 4 pixels across around the symbol.")
    return gray[y1:y2, x1:x2].copy()


def trim(gray, pad: int = 2):
    """Shrink a template to its ink plus a small margin (a loose drag still matches tightly)."""
    import numpy as np
    ys, xs = np.nonzero(ink(gray))
    if len(xs) == 0:
        raise ValueError("The box has no linework in it.")
    h, w = gray.shape[:2]
    return gray[max(ys.min() - pad, 0):min(ys.max() + pad + 1, h), max(xs.min() - pad, 0):min(xs.max() + pad + 1, w)].copy()


def custom_mask(png_gray, shape):
    """A user mask (white = scored) as a binary array the template's size."""
    import cv2
    import numpy as np
    m = png_gray
    if m.shape[:2] != tuple(shape[:2]):
        m = cv2.resize(m, (shape[1], shape[0]), interpolation=cv2.INTER_NEAREST)
    return np.where(m > 127, 255, 0).astype(np.uint8)


def effective_mask(mode: str, gray, buffer_space: int, custom=None):
    """The mask a template is matched with, or None for the whole rectangle."""
    if mode == "none":
        return None
    if mode == "custom" and custom is not None:
        return custom_mask(custom, gray.shape)
    return make_mask(gray, buffer_space)
