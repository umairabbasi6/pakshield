import pytest
from pakshield.normalizer import (
    DASH_CHARS, fold_for_matching, normalize_dashes, normalize_token,
    to_ascii_digits,
)


def test_ascii_unchanged():
    assert normalize_token("37405-1234567-1") == "37405-1234567-1"


def test_urdu_digits():
    assert to_ascii_digits("۳۷۴۰۵۱۲۳۴۵۶۷۱") == "3740512345671"


def test_arabic_indic_digits():
    assert to_ascii_digits("٣٧٤٠٥") == "37405"


def test_mixed_digit_sets():
    assert to_ascii_digits("3۷4٠5") == "37405"


def test_devanagari_not_converted():
    assert to_ascii_digits("१२३") == "१२३"


def test_all_seven_dashes_normalized():
    assert len(DASH_CHARS) == 7
    assert normalize_dashes("1" + "".join(DASH_CHARS) + "2") == "1" + "-" * 7 + "2"


def test_urdu_full_stop_is_not_a_dash():
    s = "یہ میرا نمبر ہے۔"
    assert normalize_dashes(s) == s
    assert "-" not in normalize_token(s)


@pytest.mark.parametrize("s", [
    "۳۷۴۰۵–۱۲۳۴۵۶۷–۱",
    "cnic: ٣٧٤٠٥-١٢٣٤٥٦٧-١۔",
    "plain text, no digits",
])
def test_length_preserved(s):
    assert len(normalize_token(s)) == len(s)


def test_fold_unifies_letters_and_drops_joiners():
    arabic_yeh = "شناخت\u064a"
    farsi_yeh = "شناخت\u06cc"
    assert fold_for_matching(arabic_yeh) == fold_for_matching(farsi_yeh)
    assert fold_for_matching("CN\u200cIC") == "cnic"


import unicodedata

from pakshield.normalizer import normalize_spaces


@pytest.mark.parametrize("sp", ["\u00a0", "\u202f", "\u2009", "\u3000", "\u2003"])
def test_unicode_spaces_become_ascii_space(sp):
    assert normalize_spaces(f"a{sp}b") == "a b"
    assert normalize_token(f"1{sp}2") == "1 2"


def test_all_zs_characters_are_one_to_one():
    zs = "".join(chr(c) for c in range(0x10000) if unicodedata.category(chr(c)) == "Zs")
    out = normalize_spaces(zs)
    assert len(out) == len(zs)
    assert set(out) == {" "}


def test_non_space_characters_untouched_by_spaces():
    s = "abc۔-\n\t"
    assert normalize_spaces(s) == s
