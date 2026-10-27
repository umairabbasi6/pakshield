"""Digit, dash, space and letter normalization helpers.

Two kinds of functions live here:

* Span-safe (``normalize_token`` and its parts): every character maps to
  exactly one character, so string length never changes. Offsets found in
  the normalized text are valid in the original text.
* Match-only (``fold_for_matching``): may change length. Use it ONLY for
  ad-hoc keyword comparison, never to compute offsets.
"""
from __future__ import annotations

import unicodedata

# Only these digit ranges are accepted: ASCII, Arabic-Indic, Extended
# Arabic-Indic (Urdu/Persian). Other Unicode digits (e.g. Devanagari) are
# deliberately NOT treated as CNIC digits.
PK_DIGIT_CLASS = "0-9\u0660-\u0669\u06f0-\u06f9"

# Hyphen-like characters (exactly 7). U+06D4 (Urdu full stop) is
# intentionally absent.
DASH_CHARS = "-\u2010\u2011\u2012\u2013\u2014\u2212"
DASH_CLASS = "\\-\u2010\u2011\u2012\u2013\u2014\u2212"

_DIGIT_MAP = {
    ord(ch): str(unicodedata.decimal(ch))
    for ch in (
        [chr(c) for c in range(0x0660, 0x066A)]
        + [chr(c) for c in range(0x06F0, 0x06FA)]
    )
}
_DASH_MAP = {ord(ch): "-" for ch in DASH_CHARS}

# Every Unicode space separator (category Zs) except ASCII space itself.
_SPACE_MAP = {
    c: " "
    for c in range(0x10000)
    if c != 0x20 and unicodedata.category(chr(c)) == "Zs"
}

# Letter variants for keyword matching only (not length-preserving).
_FOLD_MAP = {
    0x064A: "\u06cc",  # ARABIC YEH -> FARSI YEH
    0x0649: "\u06cc",  # ALEF MAKSURA -> FARSI YEH
    0x0643: "\u06a9",  # ARABIC KAF -> KEHEH
}
_INVISIBLE = {0x200C, 0x200D, 0x200E, 0x200F}  # ZWNJ, ZWJ, LRM, RLM


def to_ascii_digits(text: str) -> str:
    """Convert ASCII/Arabic-Indic/Urdu digits to ASCII. Length-preserving."""
    return text.translate(_DIGIT_MAP)


def normalize_dashes(text: str) -> str:
    """Map the 7 hyphen-like codepoints to ASCII '-'. Length-preserving."""
    return text.translate(_DASH_MAP)


def normalize_spaces(text: str) -> str:
    """Map every Unicode space separator (Zs) to ASCII ' '. Length-preserving."""
    return text.translate(_SPACE_MAP)


def normalize_token(text: str) -> str:
    """Digits, dashes and spaces to ASCII. Length-preserving (span-safe)."""
    out = normalize_spaces(normalize_dashes(to_ascii_digits(text)))
    if len(out) != len(text):  # invariant; must survive python -O
        raise RuntimeError("normalize_token changed string length")
    return out


def fold_for_matching(text: str) -> str:
    """Casefold, unify Urdu/Arabic letter variants, drop invisible joiners.

    NOT length-preserving. Not used by the scanner (which matches keywords
    with variant-aware regexes on the original text instead).
    """
    text = "".join(ch for ch in text if ord(ch) not in _INVISIBLE)
    return text.translate(_FOLD_MAP).casefold()
