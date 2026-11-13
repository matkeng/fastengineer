# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Proper case that keeps a project's acronyms: "mcc-01 feed to plc" -> "MCC-01 Feed To PLC".

The words come from the project's **xProper** enum (keylists.enums). Each is put back exactly
as it is written there wherever it appears with no letter either side (digits are fine: "7.5kW", "MCC01"), whatever its case, so "I/O",
"P&ID" or "kW" work too. Whoever serves a request says which words apply with
`use_proper_words` (the engine does it once per request); otherwise the defaults apply.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from contextvars import ContextVar

DEFAULT_PROPER_WORDS: tuple[str, ...] = (
    "MCC", "PLC", "VSD", "DOL", "HMI", "UPS", "SCADA", "RTD", "I/O", "P&ID", "LV", "MV", "HV", "AC", "DC", "MCB", "MCCB", "RCD",
    "ELCB", "CT", "VT", "ESD", "JB", "LCS", "IP")

Source = Iterable[str] | Callable[[], Iterable[str]]
PROPER_WORDS: ContextVar[Source | None] = ContextVar("proper_words", default=None)
_WORD = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)*")  # runs of letters (digits split words, as str.title() does)
_cache: dict[tuple[str, ...], re.Pattern[str] | None] = {}


def use_proper_words(source: Source | None):
    """Make `source` (words, or a function giving them, called once when first needed) the words
    of this context. Returns the token to reset it with."""
    if callable(source):
        loader, got = source, []

        def once() -> Iterable[str]:
            if not got:
                got.append(tuple(loader()))
            return got[0]
        return PROPER_WORDS.set(once)
    return PROPER_WORDS.set(source)


def current_words() -> tuple[str, ...]:
    src = PROPER_WORDS.get()
    if src is None:
        return DEFAULT_PROPER_WORDS
    try:
        return tuple(src() if callable(src) else src)
    except Exception:  # noqa: BLE001 - a project that can't be read: proper case still works
        return DEFAULT_PROPER_WORDS


def _pattern(words: tuple[str, ...]) -> re.Pattern[str] | None:
    if words not in _cache:
        clean = sorted({w.strip() for w in words if w.strip()}, key=len, reverse=True)
        _cache[words] = re.compile(r"(?<![^\W\d_])(" + "|".join(re.escape(w) for w in clean) + r")(?![^\W\d_])", re.IGNORECASE) if clean else None
        if len(_cache) > 64:
            _cache.pop(next(iter(_cache)))
    return _cache[words]


def proper_case(text: str, words: Iterable[str] | None = None) -> str:
    """Each word's first letter upper case and the rest lower case ("o'clock" stays "O'clock"),
    then each of `words` (default: this context's xProper words) as written."""
    out = _WORD.sub(lambda m: m.group(0)[:1].upper() + m.group(0)[1:].lower(), text)
    ws = tuple(words) if words is not None else current_words()
    pat = _pattern(ws)
    if pat is None:
        return out
    exact = {w.strip().casefold(): w.strip() for w in ws if w.strip()}
    return pat.sub(lambda m: exact.get(m.group(0).casefold(), m.group(0)), out)


__all__ = ["DEFAULT_PROPER_WORDS", "PROPER_WORDS", "proper_case", "use_proper_words", "current_words"]
