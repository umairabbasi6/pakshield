"""CNIC parsing, validation and metadata.

The 13th digit of a CNIC is a gender-parity digit, not a checksum, so
structural validation alone cannot separate a CNIC from any other 13-digit
number. Use the scrubber's context scoring for free text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import AbstractSet

from .normalizer import normalize_token

# First-digit registration zone. Digit 8 (Azad Kashmir) appears in secondary
# sources only and is UNCONFIRMED; the accepted set is configurable.
REGIONS = {
    "1": "Khyber Pakhtunkhwa",
    "2": "Former FATA",
    "3": "Punjab",
    "4": "Sindh",
    "5": "Balochistan",
    "6": "Islamabad Capital Territory",
    "7": "Gilgit-Baltistan",
    "8": "Azad Jammu and Kashmir",
}
DEFAULT_ALLOWED_FIRST_DIGITS = frozenset("12345678")

_HYPHENATED = re.compile(r"([0-9]{5})-([0-9]{7})-([0-9])")
_SPACED = re.compile(r"([0-9]{5}) ([0-9]{7}) ([0-9])")
_BARE = re.compile(r"[0-9]{13}")

_SEQUENTIAL_SERIALS = frozenset({"1234567", "7654321"})


class CNICError(ValueError):
    """Raised for an invalid CNIC. Messages never echo the input."""


@dataclass(frozen=True, slots=True, repr=False)
class CNIC:
    canonical: str  # 13 ASCII digits
    gender: str  # "male" or "female"
    region: str  # where the card was FIRST REGISTERED, not current residence

    @property
    def formatted(self) -> str:
        c = self.canonical
        return f"{c[:5]}-{c[5:12]}-{c[12]}"

    def __repr__(self) -> str:
        return f"<CNIC [REDACTED] gender={self.gender} region={self.region}>"


def parse_cnic(
    value: str,
    *,
    strict: bool = False,
    allowed_first_digits: AbstractSet[str] = DEFAULT_ALLOWED_FIRST_DIGITS,
) -> CNIC:
    """Strictly parse a single CNIC string.

    Accepts only consistent separators: ``XXXXX-XXXXXXX-X``,
    ``XXXXX XXXXXXX X`` or 13 bare digits, in ASCII/Urdu/Arabic-Indic digits.
    ``strict=True`` additionally rejects obviously synthetic serials.
    """
    if not isinstance(value, str):
        raise TypeError("CNIC value must be a string.")
    norm = normalize_token(value).strip()
    for pattern in (_HYPHENATED, _SPACED):
        m = pattern.fullmatch(norm)
        if m:
            canonical = "".join(m.groups())
            break
    else:
        if _BARE.fullmatch(norm):
            canonical = norm
        else:
            raise CNICError("Invalid CNIC format: expected 13 digits.")
    if canonical[0] not in allowed_first_digits:
        raise CNICError("Invalid CNIC first digit.")
    if strict:
        serial = canonical[5:12]
        if len(set(serial)) == 1 or serial in _SEQUENTIAL_SERIALS:
            raise CNICError("Synthetic CNIC serial rejected (strict mode).")
    return CNIC(
        canonical=canonical,
        gender="male" if int(canonical[12]) % 2 == 1 else "female",
        region=REGIONS.get(canonical[0], "Unknown"),
    )


def is_valid_cnic(value: str, **kwargs) -> bool:
    try:
        parse_cnic(value, **kwargs)
    except (CNICError, TypeError):
        return False
    return True
