import dataclasses

import pytest

from pakshield import CNIC, CNICError, is_valid_cnic, parse_cnic

A = "37405-8765432-1"  # synthetic
URDU = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def ur(s):
    return s.translate(URDU)


def test_hyphenated_spaced_bare():
    for v in (A, "37405 8765432 1", "3740587654321"):
        c = parse_cnic(v)
        assert c.canonical == "3740587654321"
        assert c.formatted == A


def test_urdu_digits_and_nbsp():
    assert parse_cnic(ur(A)).canonical == "3740587654321"
    assert parse_cnic("37405\u00a08765432\u202f1").canonical == "3740587654321"
    assert parse_cnic("  37405–8765432–1  ").canonical == "3740587654321"


@pytest.mark.parametrize("d,region", [
    ("1", "Khyber Pakhtunkhwa"), ("2", "Former FATA"), ("3", "Punjab"),
    ("4", "Sindh"), ("5", "Balochistan"), ("6", "Islamabad Capital Territory"),
    ("7", "Gilgit-Baltistan"), ("8", "Azad Jammu and Kashmir"),
])
def test_regions_for_default_digits(d, region):
    assert parse_cnic(d + "2345" + "8765432" + "1").region == region


@pytest.mark.parametrize("d", ["0", "9"])
def test_invalid_first_digit(d):
    with pytest.raises(CNICError):
        parse_cnic(d + "37408765432" + "1")


def test_allowed_first_digits_configurable():
    v = "8110123456781"
    assert is_valid_cnic(v)
    assert not is_valid_cnic(v, allowed_first_digits=frozenset("1234567"))


def test_gender_parity():
    assert parse_cnic("3740587654321").gender == "male"
    assert parse_cnic("3740587654322").gender == "female"


@pytest.mark.parametrize("v", [
    "374058765432", "37405876543210", "37405-8765432-12", "",
    "37405-8765432 1", "37405 8765432-1", "37405 - 8765432 - 1",
    "abcde-fghijkl-m", "37405-876543-21",
])
def test_rejected_shapes(v):
    assert not is_valid_cnic(v)


def test_strict_rejects_synthetic_serials_default_does_not():
    for serial in ("0000000", "1111111", "1234567", "7654321"):
        v = "35202" + serial + "1"
        assert is_valid_cnic(v)
        assert not is_valid_cnic(v, strict=True)
    assert is_valid_cnic("3520287654321", strict=True)


def test_repr_and_str_never_show_number():
    c = parse_cnic(A)
    assert repr(c) == "<CNIC [REDACTED] gender=male region=Punjab>"
    assert str(c) == repr(c)
    assert "37405" not in repr(c) and "3740587654321" not in f"{c!r}"


def test_errors_do_not_echo_input():
    for bad in ("98765-4321098-7", "123", "37405-8765432 1"):
        with pytest.raises(CNICError) as e:
            parse_cnic(bad)
        msg = str(e.value)
        assert "98765" not in msg and "4321098" not in msg and "8765432" not in msg


def test_non_string_raises_type_error():
    with pytest.raises(TypeError):
        parse_cnic(3740587654321)  # type: ignore[arg-type]
    assert not is_valid_cnic(None)  # type: ignore[arg-type]


def test_frozen():
    c = parse_cnic(A)
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.canonical = "x"  # type: ignore[misc]
