# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Symbol matching with OpenCV (PRD 5.6), with the PRD 11 defects fixed:

- page and template are both binarised ink images, matched with mean-subtracted
  normalised correlation under the stroke mask, so scores aren't high everywhere (#14);
- peaks are picked by score with non-max suppression, not raster order (#11);
- a template with too many candidates is reported, not silently dropped (#12);
- every box is in full-size page pixels, also when the downscale guard fires (#3);
- page overrides (threshold / ignore) are applied (#1).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import Box, PageOverride, SkippedTemplate, Symbol, Template
from .templates import effective_mask, ink

MAX_PIXELS = 80_000_000  # downscale guard (PRD 5.6 step 1)


@dataclass
class TemplateImage:
    template: Template
    gray: object  # uint8 array
    mask: object | None = None  # uint8 array, or None to score the whole rectangle


@dataclass
class MatchOutput:
    symbols: list[Symbol] = field(default_factory=list)
    skipped: list[SkippedTemplate] = field(default_factory=list)
    best: dict[str, float] = field(default_factory=dict)  # template id -> best score seen


def _variants(t: Template, img, mask):
    import numpy as np
    out = [("0", img, mask)]
    v = t.variants
    for name, k, on in (("90", 1, v.rot90), ("180", 2, v.rot180), ("270", 3, v.rot270)):
        if on:
            out.append((name, np.ascontiguousarray(np.rot90(img, -k)),
                        None if mask is None else np.ascontiguousarray(np.rot90(mask, -k))))
    if v.mirror:
        out += [(f"{n}m", np.ascontiguousarray(np.fliplr(i)), None if m is None else np.ascontiguousarray(np.fliplr(m)))
                for n, i, m in list(out)]
    return out


def _iou(a: Box, b: Box) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    if inter <= 0:
        return 0.0
    return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter)


def nms(cands: list[tuple[float, Box, str]], iou: float = 0.3) -> list[tuple[float, Box, str]]:
    keep: list[tuple[float, Box, str]] = []
    for c in sorted(cands, key=lambda c: -c[0]):
        if all(_iou(c[1], k[1]) < iou for k in keep):
            keep.append(c)
    return keep


def masked_ncc(work01, t_ink, mask):
    """Mean-subtracted normalised correlation restricted to the mask (what
    TM_CCOEFF_NORMED with a mask computes), built from two FFT correlations so it is
    several times faster than OpenCV's direct masked path. Windows with (almost) no
    variation under the mask score 0 instead of a meaningless value."""
    import cv2
    import numpy as np
    m = (mask > 0).astype(np.float32) if mask is not None else np.ones(t_ink.shape, np.float32)
    n = float(m.sum())
    t = (t_ink > 0).astype(np.float32)
    mean_t = float((t * m).sum()) / n
    t0 = (t - mean_t) * m
    t_norm = float(np.sqrt((t0 * t0).sum()))
    if n < 4 or t_norm < 1e-6:
        return None
    num = cv2.matchTemplate(work01, t0, cv2.TM_CCORR)
    s1 = cv2.matchTemplate(work01, m, cv2.TM_CCORR)  # ink under the mask (binary: sum I^2 == sum I)
    var = s1 - s1 * s1 / n
    ok = var > max(1.0, 0.002 * n)
    res = np.zeros_like(num)
    res[ok] = num[ok] / (t_norm * np.sqrt(var[ok]))
    return np.clip(res, -1.0, 1.0)


def _candidates(work01, tmpl, mask, threshold: float, min_cover: float = 0.6):
    """Local maxima of the score map at or above threshold: [(score, x, y)], plus the best score.
    A candidate must also have ink under most of the template's strokes (min_cover)."""
    import cv2
    import numpy as np
    th, tw = tmpl.shape[:2]
    if th > work01.shape[0] or tw > work01.shape[1]:
        return [], 0.0
    t_ink = ink(tmpl)
    res = masked_ncc(work01, t_ink, mask)
    if res is None:
        return [], 0.0
    best = float(res.max()) if res.size else 0.0
    k = np.ones((max(th // 2, 3), max(tw // 2, 3)), np.uint8)
    peaks = (res >= threshold) & (res >= cv2.dilate(res, k))
    ys, xs = np.nonzero(peaks)
    strokes = t_ink > 0
    n_strokes = max(int(strokes.sum()), 1)
    out = []
    for y, x in zip(ys, xs):
        patch = work01[y:y + th, x:x + tw] > 0
        if (patch & strokes).sum() / n_strokes >= min_cover:
            out.append((float(res[y, x]), int(x), int(y)))
    return out, best


def locate_symbols(gray, templates: list[TemplateImage], overrides: dict[str, PageOverride] | None = None,
                   whiteout: bool = True) -> MatchOutput:
    """Match templates in priority order; each accepted symbol is erased before the next
    template runs, so a specific symbol (control valve) placed first isn't re-claimed by a
    generic one (valve body)."""
    import cv2
    overrides = overrides or {}
    out = MatchOutput()
    h, w = gray.shape[:2]
    scale = 1.0
    if h * w > MAX_PIXELS:
        scale = (MAX_PIXELS / (h * w)) ** 0.5
        gray = cv2.resize(gray, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    work = (ink(gray) > 0).astype('float32')  # 1 = ink, 0 = paper

    for ti in sorted(templates, key=lambda t: t.template.priority):
        t = ti.template
        if not t.active:
            continue
        ov = overrides.get(t.id)
        if ov and ov.ignore:
            continue
        threshold = ov.threshold if ov and ov.threshold is not None else t.threshold
        cands: list[tuple[float, Box, str]] = []
        best = 0.0
        for factor in t.scales or [1.0]:
            f = factor * scale
            timg, tmask = ti.gray, ti.mask
            if f != 1.0:
                size = (max(int(round(timg.shape[1] * f)), 2), max(int(round(timg.shape[0] * f)), 2))
                timg = cv2.resize(timg, size, interpolation=cv2.INTER_AREA)
                if tmask is not None:
                    tmask = cv2.resize(tmask, size, interpolation=cv2.INTER_NEAREST)
            for vname, vimg, vmask in _variants(t, timg, tmask):
                vh, vw = vimg.shape[:2]
                found, b = _candidates(work, vimg, vmask, threshold)
                best = max(best, b)
                label = vname if factor == 1.0 else f"{vname}@{factor:g}"
                cands += [(s, [x, y, x + vw, y + vh], label) for s, x, y in found]
        out.best[t.id] = round(best, 4)
        if len(cands) > t.max_hits:
            out.skipped.append(SkippedTemplate(
                template_id=t.id, desc=t.desc, hits=len(cands),
                reason=f"{len(cands)} candidates above {threshold:.2f} (limit {t.max_hits}); "
                       "raise the threshold or override it for this page."))
            continue
        for score, box, vname in nms(cands):
            x1, y1, x2, y2 = (int(v) for v in box)
            if whiteout:
                work[y1:y2, x1:x2] = 0
            full = [round(v / scale, 1) for v in box]
            out.symbols.append(Symbol(template_id=t.id, template_desc=t.desc, box=full,
                                      score=round(score, 4), variant=vname))
    return out


def prepare(template: Template, gray, custom_mask=None) -> TemplateImage:
    """custom_mask: the user's mask image (greyscale array), used when mask_mode is "custom"."""
    return TemplateImage(template, gray, effective_mask(template.mask_mode, gray, template.buffer_space, custom_mask))


def locate_near(gray, ti: TemplateImage, x: float, y: float, reach: float = 1.0) -> Symbol | None:
    """The best placement of one template around a clicked point, whatever its score: how a
    symbol the matcher missed is added by hand. `gray` is the text-free page (as for
    locate_symbols); the search window is the template's size plus `reach` of it each side,
    so the click needn't be exact. Returns None only when the template can't be scored."""
    import cv2
    t = ti.template
    h, w = gray.shape[:2]
    best: tuple[float, Box, str] | None = None
    for factor in t.scales or [1.0]:
        timg, tmask = ti.gray, ti.mask
        if factor != 1.0:
            size = (max(int(round(timg.shape[1] * factor)), 2), max(int(round(timg.shape[0] * factor)), 2))
            timg = cv2.resize(timg, size, interpolation=cv2.INTER_AREA)
            if tmask is not None:
                tmask = cv2.resize(tmask, size, interpolation=cv2.INTER_NEAREST)
        for vname, vimg, vmask in _variants(t, timg, tmask):
            vh, vw = vimg.shape[:2]
            x1 = max(int(x - vw / 2 - vw * reach), 0)
            y1 = max(int(y - vh / 2 - vh * reach), 0)
            x2 = min(int(x + vw / 2 + vw * reach) + 1, w)
            y2 = min(int(y + vh / 2 + vh * reach) + 1, h)
            if x2 - x1 < vw or y2 - y1 < vh:
                continue
            work = (ink(gray[y1:y2, x1:x2]) > 0).astype('float32')
            res = masked_ncc(work, ink(vimg), vmask)
            if res is None or not res.size:
                continue
            _, score, _, (px, py) = cv2.minMaxLoc(res)
            label = vname if factor == 1.0 else f"{vname}@{factor:g}"
            if best is None or score > best[0]:
                best = (float(score), [float(x1 + px), float(y1 + py), float(x1 + px + vw), float(y1 + py + vh)], label)
    if best is None:
        return None
    score, box, vname = best
    return Symbol(template_id=t.id, template_desc=t.desc, box=box, score=round(max(score, 0.0), 4),
                  variant=vname, origin="manual")
