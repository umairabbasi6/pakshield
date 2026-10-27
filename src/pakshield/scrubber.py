"""Context-aware CNIC detection, reversible redaction and restoration."""
from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from typing import AbstractSet, Dict, List, Optional, Set, Tuple

from .cnic import CNIC, DEFAULT_ALLOWED_FIRST_DIGITS, CNICError, parse_cnic
from .normalizer import DASH_CLASS, normalize_token

# --- scoring (integers; no float drift) -----------------------------------
SCORE_HYPHENATED = 80  # 12345-1234567-1
SCORE_COMPOUND = 50  # same, but glued to a leading/trailing '-'
SCORE_SPACED = 35  # 12345 1234567 1
SCORE_LOOSE = 35  # mixed or padded separators
SCORE_BARE = 20  # 13 bare digits
BOOST_STRONG = 30
BOOST_WEAK = 15
DEFAULT_MIN_SCORE = 50
CONTEXT_WINDOW = 35  # characters, measured from the candidate's edges

# --- candidate pattern (run on the length-preserving normalized text) ------
_SEP = r"(?: ?- ?| )"
_CANDIDATE_RE = re.compile(
    r"(?<![0-9])(?:"
    r"(?P<d1>[0-9]{5})(?P<s1>" + _SEP + r")(?P<d2>[0-9]{7})"
    r"(?P<s2>" + _SEP + r")(?P<d3>[0-9])"
    r"|(?P<bare>[0-9]{13})"
    r")(?![0-9])"
)

# --- keywords (run on the ORIGINAL text, so offsets are exact) -------------
_B_L = r"(?<![^\W_])"
_B_R = r"(?![^\W_])"


def _en(parts):
    return re.compile(_B_L + "(?:" + "|".join(parts) + ")" + _B_R, re.IGNORECASE)


_EN_STRONG = _en([r"cnic", r"c\.n\.i\.c\.?", r"nadra", r"nicop", r"shanakhti"])
_EN_WEAK = _en([r"nic", r"b[" + DASH_CLASS + r"\s]?form"])

_IGN = "[\u200b-\u200f\u202a-\u202e\u2066-\u2069\u0640\u064b-\u065f\u0670]*"
_SP = r"[\s\u200b-\u200f\u202a-\u202e\u2066-\u2069]+"
_VARIANTS = {"ی": "[\u06cc\u064a]", "ک": "[\u06a9\u0643]"}


def _urdu(phrase: str):
    words = []
    for word in phrase.split(" "):
        words.append(_IGN.join(_VARIANTS.get(ch, re.escape(ch)) for ch in word))
    return _SP.join(words)


_MARKS = "\u0640\u064b-\u065f\u0670"  # tatweel + harakat: not \w, but part of a word


def _ur(parts):
    # Left: not preceded by a letter or by a mark that belongs to a letter.
    # Right: trailing marks on the last letter are allowed, then no letter.
    return re.compile(
        _B_L + "(?<![" + _MARKS + "])(?:" + "|".join(parts) + ")" + _IGN
        # without this, backtracking gives the mark back and \W passes the
        # boundary in the middle of a vocalized word
        + "(?![" + _MARKS + "])" + _B_R
    )


_UR_STRONG = _ur([_urdu(p) for p in ("شناختی کارڈ", "قومی شناختی کارڈ", "نادرا")])
_UR_WEAK = _ur([_urdu("ب فارم")])

_KEYWORD_RES = (
    (_EN_STRONG, BOOST_STRONG),
    (_UR_STRONG, BOOST_STRONG),
    (_EN_WEAK, BOOST_WEAK),
    (_UR_WEAK, BOOST_WEAK),
)

# --- placeholders -----------------------------------------------------------
_PLACEHOLDER_RE = re.compile(
    r"\[\s*cnic[\s_-]*([0-9]+)\s*\]", re.IGNORECASE | re.ASCII
)
_MAX_ID_DIGITS = 9  # longer ids can never collide; avoids int() on huge input
_COLLISION_MSG = (
    "Input contains a placeholder matching an already-allocated vault ID."
)
_FORMATS = ("original", "formatted", "canonical")


class PlaceholderCollisionError(Exception):
    """Input contains a placeholder for an ID the vault already allocated."""


@dataclass(frozen=True, slots=True, repr=False)
class Detection:
    cnic: CNIC
    raw_text: str
    start: int
    end: int
    score: int

    @property
    def span(self) -> Tuple[int, int]:
        return (self.start, self.end)

    def __repr__(self) -> str:
        return (
            f"<Detection [REDACTED] score={self.score} "
            f"span={self.start}:{self.end}>"
        )


class RedactionVault:
    """Maps placeholder ids to CNICs. Keep it in memory, one per request or
    conversation. Masked repr is a logging safeguard, not a security
    boundary."""

    __slots__ = ("_id_to_entry", "_canonical_to_id", "_reserved", "_next_id")

    def __init__(self) -> None:
        self._id_to_entry: Dict[int, Tuple[CNIC, str]] = {}
        self._canonical_to_id: Dict[str, int] = {}
        self._reserved: Set[int] = set()
        self._next_id = 1

    def __len__(self) -> int:
        return len(self._id_to_entry)

    def __repr__(self) -> str:
        return f"<RedactionVault [REDACTED] entries={len(self)}>"

    # pickling is blocked so vaults never reach Redis/disk/queues by accident
    def __getstate__(self):
        raise TypeError("RedactionVault cannot be pickled.")

    def __reduce__(self):
        raise TypeError("RedactionVault cannot be pickled.")

    def __reduce_ex__(self, protocol):
        raise TypeError("RedactionVault cannot be pickled.")

    def __deepcopy__(self, memo):
        new = type(self)()
        new._id_to_entry = dict(self._id_to_entry)
        new._canonical_to_id = dict(self._canonical_to_id)
        new._reserved = set(self._reserved)
        new._next_id = self._next_id
        return new

    def _is_allocated(self, n: int) -> bool:
        return n in self._id_to_entry

    def _reserve_all(self, ids) -> None:
        self._reserved.update(ids)

    def _allocate(self, cnic: CNIC, raw: str) -> int:
        existing = self._canonical_to_id.get(cnic.canonical)
        if existing is not None:
            return existing
        n = self._next_id
        while n in self._id_to_entry or n in self._reserved:
            n += 1
        self._next_id = n + 1
        self._id_to_entry[n] = (cnic, raw)
        self._canonical_to_id[cnic.canonical] = n
        return n

    def _lookup(self, n: int) -> Optional[Tuple[CNIC, str]]:
        return self._id_to_entry.get(n)


def _vault_copy(self, *args):
    return self.__deepcopy__({})


RedactionVault.__copy__ = _vault_copy  # type: ignore[attr-defined]


def _keyword_spans(text: str) -> List[Tuple[int, int, int]]:
    spans = []
    for rx, boost in _KEYWORD_RES:
        for m in rx.finditer(text):
            spans.append((m.start(), m.end(), boost))
    spans.sort()  # by start; lets _context_boost bisect instead of scanning all
    return spans


def _context_boost(start: int, end: int, spans, starts=None) -> int:
    """Strongest single keyword fully inside the window; boosts never stack."""
    if starts is None:
        starts = [k[0] for k in spans]
    best = 0
    lo = bisect_left(starts, start - CONTEXT_WINDOW)
    hi = bisect_right(starts, end + CONTEXT_WINDOW)
    for k_start, k_end, boost in spans[lo:hi]:
        left = start - CONTEXT_WINDOW <= k_start and k_end <= start
        right = end <= k_start and k_end <= end + CONTEXT_WINDOW
        if (left or right) and boost > best:
            best = boost
    return best


def scan(
    text: str,
    *,
    min_score: int = DEFAULT_MIN_SCORE,
    strict: bool = False,
    allowed_first_digits: AbstractSet[str] = DEFAULT_ALLOWED_FIRST_DIGITS,
) -> List[Detection]:
    """Find CNICs in free text. Offsets refer to the original ``text``."""
    norm = normalize_token(text)
    spans = _keyword_spans(text)
    starts = [k[0] for k in spans]
    found: List[Detection] = []
    for m in _CANDIDATE_RE.finditer(norm):
        start, end = m.span()
        if m.group("bare") is not None:
            digits, base = m.group("bare"), SCORE_BARE
        else:
            digits = m.group("d1") + m.group("d2") + m.group("d3")
            s1, s2 = m.group("s1"), m.group("s2")
            if s1 == "-" and s2 == "-":
                glued = (start > 0 and norm[start - 1] == "-") or (
                    end < len(norm) and norm[end] == "-"
                )
                base = SCORE_COMPOUND if glued else SCORE_HYPHENATED
            elif s1 == " " and s2 == " ":
                base = SCORE_SPACED
            else:
                base = SCORE_LOOSE
        try:
            cnic = parse_cnic(
                digits, strict=strict, allowed_first_digits=allowed_first_digits
            )
        except CNICError:
            continue
        score = min(100, base + _context_boost(start, end, spans, starts))
        if score >= min_score:
            found.append(Detection(cnic, text[start:end], start, end, score))
    return found


def _placeholder_ids(text: str) -> Set[int]:
    ids = set()
    for m in _PLACEHOLDER_RE.finditer(text):
        digits = m.group(1)
        if len(digits) <= _MAX_ID_DIGITS:
            ids.add(int(digits))
    return ids


def redact(
    text: str,
    vault: Optional[RedactionVault] = None,
    *,
    min_score: int = DEFAULT_MIN_SCORE,
    strict: bool = False,
    allowed_first_digits: AbstractSet[str] = DEFAULT_ALLOWED_FIRST_DIGITS,
) -> Tuple[str, RedactionVault]:
    """Replace detected CNICs with ``[CNIC_n]``.

    Call only on NEW untrusted input, never on text that already went
    through this vault. Raises PlaceholderCollisionError if the input holds
    a placeholder for an id this vault already allocated.
    """
    if vault is None:
        vault = RedactionVault()
    # Pass 1: check every existing placeholder first (atomic), then reserve.
    existing = _placeholder_ids(text)
    for n in existing:
        if vault._is_allocated(n):
            raise PlaceholderCollisionError(_COLLISION_MSG)
    vault._reserve_all(existing)
    # Pass 2: detect and allocate.
    pieces: List[str] = []
    last = 0
    for d in scan(
        text,
        min_score=min_score,
        strict=strict,
        allowed_first_digits=allowed_first_digits,
    ):
        n = vault._allocate(d.cnic, d.raw_text)
        pieces.append(text[last : d.start])
        pieces.append(f"[CNIC_{n}]")
        last = d.end
    pieces.append(text[last:])
    return "".join(pieces), vault


def restore(text: str, vault: RedactionVault, *, fmt: str = "original") -> str:
    """Put CNICs back. Placeholders the vault never allocated are left as is.

    ``original`` restores the first-seen raw form for every occurrence of
    the same CNIC; ``formatted`` gives ``XXXXX-XXXXXXX-X``; ``canonical``
    gives 13 digits.
    """
    if fmt not in _FORMATS:
        raise ValueError("fmt must be one of: original, formatted, canonical.")

    def _sub(m: "re.Match[str]") -> str:
        digits = m.group(1)
        if len(digits) > _MAX_ID_DIGITS:
            return m.group(0)
        entry = vault._lookup(int(digits))
        if entry is None:
            return m.group(0)
        cnic, raw = entry
        if fmt == "original":
            return raw
        return cnic.formatted if fmt == "formatted" else cnic.canonical

    return _PLACEHOLDER_RE.sub(_sub, text)
