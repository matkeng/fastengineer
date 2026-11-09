# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Turn symbols and page words into text tags, using the library's tag rules.

- Template tags (PRD 5.5): each tag point picks the word under it inside the symbol.
- Text scan: text anywhere on the page that matches the library's tag pattern, as one
  word ('FT-1023') or two words stacked one over the other ('FT' over '1023', as in an
  instrument bubble).
"""

from __future__ import annotations

import re
import string
from collections.abc import Iterable

from .models import Box, Exclusion, FoundTag, Library, Symbol, Template, Word

_PUNCT = string.punctuation.replace("-", "").replace("/", "").replace(".", "") + "."


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


def _format(fmt: str, values: dict[str, str]) -> str:
    try:
        return fmt.format_map(_Blank(values))
    except (ValueError, IndexError):
        return "-".join(v for v in values.values() if v)


def format_tag(t: Template, parts: dict[str, str | None]) -> str | None:
    if not parts or all(v is None for v in parts.values()):
        return None
    values = {k: v or "" for k, v in parts.items()}
    out = _format(t.tag_format, values) if t.tag_format.strip() else "-".join(v for v in values.values() if v)
    return out.strip(" -") or None


def compile_pattern(pattern: str) -> re.Pattern[str] | None:
    if not pattern.strip():
        return None
    try:
        return re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"The tag pattern is not a valid regular expression: {exc}.") from exc


def check_format(fmt: str, names: Iterable[str]) -> str | None:
    """An error message for a format string with unknown {placeholders}, else None."""
    if not fmt.strip():
        return None
    try:
        fmt.format_map({n: "X" for n in names})
    except KeyError as exc:
        return f"{{{exc.args[0]}}} is not one of: {', '.join(names) or '(none)'}."
    except (ValueError, IndexError):
        return "Use {name} placeholders, e.g. {function}-{loop}."
    return None


def group_names(lib: Library) -> list[str]:
    rx = compile_pattern(lib.tag_pattern)
    return list(rx.groupindex) if rx else []


class TagRules:
    """A library's tag pattern and output format, compiled once per page."""

    def __init__(self, lib: Library):
        self.rx = compile_pattern(lib.tag_pattern)
        self.fmt = lib.tag_format
        self.lib = lib

    def match(self, *candidates: str) -> tuple[str, dict[str, str]] | None:
        """The first candidate text that matches the pattern, as (tag, groups)."""
        if self.rx is None:
            return None
        for text in candidates:
            m = self.rx.fullmatch(text)
            if m:
                groups = {k: v or "" for k, v in m.groupdict().items()}
                tag = _format(self.fmt, groups) if self.fmt.strip() else text
                return tag.strip() or text, groups
        return None

    def normalise(self, tag: str) -> tuple[str, dict[str, str]]:
        """A template tag in the library's format, when it matches the pattern."""
        compact = re.sub(r"\s+", "", tag)
        hit = self.match(tag, compact, compact.replace("-", ""))
        return hit if hit else (tag, {})


def _clean(text: str) -> str:
    return text.strip(_PUNCT + " ")


def pattern_scan(words: list[Word], rules: TagRules, page: int = 0) -> list[FoundTag]:
    if rules.rx is None or not rules.lib.pattern_scan:
        return []
    tags: list[FoundTag] = []
    used: set[int] = set()
    cleaned = [_clean(w.text) for w in words]
    if rules.lib.scan_stacked:
        # Two words, one directly above the other and about one line apart (boxes are tight
        # around the glyphs, so a normal line gap is up to ~1.5x the text height).
        pairs = []
        order = sorted(range(len(words)), key=lambda i: words[i].box[1])
        for ii, i in enumerate(order):
            a = words[i].box
            ah = a[3] - a[1]
            ax = (a[0] + a[2]) / 2
            for j in order[ii + 1:]:
                b = words[j].box
                if b[1] > a[3] + 2 * ah:
                    break
                h = max(ah, b[3] - b[1])
                gap = b[1] - a[3]
                dx = abs(ax - (b[0] + b[2]) / 2)
                if -0.3 * h <= gap <= 1.6 * h and dx <= 0.75 * h + 0.25 * max(a[2] - a[0], b[2] - b[0]):
                    pairs.append((gap + dx, i, j))
        for _, i, j in sorted(pairs):
            if i in used or j in used or not cleaned[i] or not cleaned[j]:
                continue
            hit = rules.match(cleaned[i] + cleaned[j], f"{cleaned[i]}-{cleaned[j]}", f"{cleaned[i]} {cleaned[j]}")
            if not hit or rules.match(cleaned[i]) or rules.match(cleaned[j]):
                continue  # each word on its own is already a tag: not a stacked pair
            used |= {i, j}
            a, b = words[i].box, words[j].box
            tags.append(FoundTag(tag=hit[0], groups=hit[1], source="pattern",
                                 box=[min(a[0], b[0]), a[1], max(a[2], b[2]), b[3]], page=page))
    for i, t in enumerate(cleaned):
        if i in used or not t:
            continue
        hit = rules.match(t)
        if hit:
            tags.append(FoundTag(tag=hit[0], groups=hit[1], source="pattern", box=list(words[i].box), page=page))
    return tags


def apply_exclusion(words: list[Word], ex: Exclusion | None, width: int, height: int) -> list[Word]:
    if ex is None or (not ex.words and not ex.areas):
        return words
    drop = {w.strip().upper() for w in ex.words if w.strip()}
    areas = [[a[0] * width, a[1] * height, a[2] * width, a[3] * height] for a in ex.areas]
    return [w for w in words
            if _clean(w.text).upper() not in drop and not any(_inside(_centre(w.box), a) for a in areas)]


def symbol_tags(symbols: list[Symbol], pattern_tags: list[FoundTag], rules: TagRules, page: int = 0) -> list[FoundTag]:
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
        tag, groups = rules.normalise(s.tag)
        s.tag = tag
        out.append(FoundTag(tag=tag, groups=groups, source="template", template_desc=s.template_desc,
                            box=list(s.box), page=page))
    out += [p for i, p in enumerate(pattern_tags) if i not in claimed]
    return out
