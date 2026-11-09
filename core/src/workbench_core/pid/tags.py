"""Turn symbols and page words into instrument tags.

- Template tags (PRD 5.5): each tag point picks the word under it inside the symbol.
- Pattern scan: ISA-style tags anywhere in the page text, single words ('FT-1023') or
  the usual bubble layout of letters stacked over a number ('FT' over '1023').
"""

from __future__ import annotations

import re
import string
from collections.abc import Iterable

from .models import Box, Exclusion, FoundTag, Symbol, Template, Word

LETTERS = re.compile(r"^[A-Z]{1,5}$")
NUMBERISH = re.compile(r"^\d{2,6}[A-Z]{0,2}$")
_PUNCT = string.punctuation.replace("-", "")


def box_overlap(a: Box, b: Box) -> float:
    """Intersection / the smaller box's area (PRD calculate_box_overlap): a short word
    fully inside a big symbol scores 1.0."""
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    small = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return (ix * iy) / small if small > 0 else 0.0


def _centre(b: Box) -> tuple[float, float]:
    return (b[0] + b[2]) / 2, (b[1] + b[3]) / 2


def _inside(pt: tuple[float, float], b: Box) -> bool:
    return b[0] <= pt[0] <= b[2] and b[1] <= pt[1] <= b[3]


def point_in_symbol(t: Template, variant: str, x: float, y: float) -> tuple[float, float]:
    """Map a tag point from the template frame into a matched variant's frame."""
    w, h = t.width, t.height
    base, _, factor = variant.partition("@")
    f = float(factor) if factor else 1.0
    mirror = base.endswith("m")
    rot = base.rstrip("m") or "0"
    if rot == "90":
        x, y, w = h - y, x, h
    elif rot == "180":
        x, y = w - x, h - y
    elif rot == "270":
        x, y, w = y, w - x, h
    if mirror:
        x = w - x
    return x * f, y * f


def resolve_points(symbol: Symbol, t: Template, words: Iterable[Word]) -> dict[str, str | None]:
    words = list(words)
    parts: dict[str, str | None] = {}
    for p in t.points:
        dx, dy = point_in_symbol(t, symbol.variant, p.x, p.y)
        pt = (symbol.box[0] + dx, symbol.box[1] + dy)
        hits = [w.text for w in words if _inside(pt, w.box) and box_overlap(w.box, symbol.box) >= p.min_overlap]
        parts[p.name] = " ".join(hits) if hits else None
    return parts


class _Blank(dict):
    def __missing__(self, key: str) -> str:
        return ""


def format_tag(t: Template, parts: dict[str, str | None]) -> str | None:
    if not parts or all(v is None for v in parts.values()):
        return None
    if t.tag_format.strip():
        try:
            out = t.tag_format.format_map(_Blank({k: v or "" for k, v in parts.items()}))
        except (ValueError, IndexError):
            out = "-".join(v for v in parts.values() if v)
    else:
        out = "-".join(v for v in parts.values() if v)
    return out.strip(" -") or None


def compile_pattern(pattern: str) -> re.Pattern[str]:
    try:
        rx = re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"The tag pattern is not a valid regular expression: {exc}.") from exc
    missing = {"function", "loop"} - set(rx.groupindex)
    if missing:
        raise ValueError("The tag pattern needs named groups (?P<function>...) and (?P<loop>...).")
    return rx


def split_tag(tag: str, rx: re.Pattern[str]) -> tuple[str, str, str]:
    m = rx.match(tag.replace(" ", "")) or rx.match(tag)
    if not m:
        return "", "", ""
    g = m.groupdict()
    return g.get("function") or "", g.get("loop") or "", g.get("suffix") or ""


def canonical(function: str, loop: str, suffix: str) -> str:
    return f"{function}-{loop}{suffix}"


def _clean(text: str) -> str:
    return text.strip(_PUNCT + " ")


def pattern_scan(words: list[Word], rx: re.Pattern[str], page: int = 0) -> list[FoundTag]:
    tags: list[FoundTag] = []
    used: set[int] = set()
    cleaned = [_clean(w.text) for w in words]
    # Stacked bubbles first: letters directly above a number, about one line apart.
    tops = [i for i, t in enumerate(cleaned) if LETTERS.match(t)]
    bottoms = [i for i, t in enumerate(cleaned) if NUMBERISH.match(t)]
    pairs = []
    for i in tops:
        a = words[i].box
        ah = a[3] - a[1]
        ax, _ = _centre(a)
        for j in bottoms:
            b = words[j].box
            bh = b[3] - b[1]
            bx, _ = _centre(b)
            gap = b[1] - a[3]
            h = max(ah, bh)
            if -0.3 * h <= gap <= 0.9 * h and abs(ax - bx) <= 0.75 * h + 0.25 * max(a[2] - a[0], b[2] - b[0]):
                pairs.append((gap + abs(ax - bx), i, j))
    for _, i, j in sorted(pairs):
        if i in used or j in used:
            continue
        m = rx.match(cleaned[i] + cleaned[j])
        if not m:
            continue
        used |= {i, j}
        g = m.groupdict()
        a, b = words[i].box, words[j].box
        f, lp, sx = g.get("function") or "", g.get("loop") or "", g.get("suffix") or ""
        tags.append(FoundTag(tag=canonical(f, lp, sx), function=f, loop=lp, suffix=sx, source="pattern",
                             box=[min(a[0], b[0]), a[1], max(a[2], b[2]), b[3]], page=page))
    for i, t in enumerate(cleaned):
        if i in used:
            continue
        m = rx.match(t)
        if m:
            g = m.groupdict()
            f, lp, sx = g.get("function") or "", g.get("loop") or "", g.get("suffix") or ""
            tags.append(FoundTag(tag=canonical(f, lp, sx), function=f, loop=lp, suffix=sx,
                                 source="pattern", box=list(words[i].box), page=page))
    return tags


def apply_exclusion(words: list[Word], ex: Exclusion | None, width: int, height: int) -> list[Word]:
    if ex is None or (not ex.words and not ex.areas):
        return words
    drop = {w.strip().upper() for w in ex.words if w.strip()}
    areas = [[a[0] * width, a[1] * height, a[2] * width, a[3] * height] for a in ex.areas]
    return [w for w in words
            if _clean(w.text).upper() not in drop and not any(_inside(_centre(w.box), a) for a in areas)]


def symbol_tags(symbols: list[Symbol], pattern_tags: list[FoundTag], rx: re.Pattern[str],
                page: int = 0) -> list[FoundTag]:
    """Template tags win; a pattern tag inside a matched symbol is dropped (or fills in a
    symbol whose tag points found nothing)."""
    out: list[FoundTag] = []
    claimed: set[int] = set()
    for s in symbols:
        inside = [i for i, p in enumerate(pattern_tags) if i not in claimed and _inside(_centre(p.box), s.box)]
        claimed.update(inside)
        if s.tag is None and inside:
            s.tag = pattern_tags[inside[0]].tag
        if s.tag is None:
            continue
        f, lp, sx = split_tag(s.tag, rx)
        tag = canonical(f, lp, sx) if f and lp else s.tag
        out.append(FoundTag(tag=tag, function=f, loop=lp, suffix=sx, source="template",
                            template_desc=s.template_desc, box=list(s.box), page=page))
    out += [p for i, p in enumerate(pattern_tags) if i not in claimed]
    return out
