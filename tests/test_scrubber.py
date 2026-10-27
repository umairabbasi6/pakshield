import copy
import pickle

import pytest

from pakshield import (
    PlaceholderCollisionError, RedactionVault, redact, restore, scan,
)

A = "37405-8765432-1"
A_CAN = "3740587654321"
B = "42101-2468013-4"
URDU = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def ur(s):
    return s.translate(URDU)


def scores(text, **kw):
    return [d.score for d in scan(text, **kw)]


# ---------------- scoring tiers ----------------
def test_standalone_hyphenated_80_and_capped_with_keyword():
    assert scores(f"Number is {A}") == [80]
    assert scores(f"CNIC {A}") == [100]


def test_detection_span_and_repr():
    t = f"Number is {A}"
    (d,) = scan(t)
    assert d.span == (10, 25) and t[d.start:d.end] == A == d.raw_text
    assert repr(d) == "<Detection [REDACTED] score=80 span=10:25>"
    assert A_CAN not in repr(d)


def test_compound_hyphen_scores_50_and_excludes_punctuation():
    (d,) = scan("number—" + A)
    assert d.score == 50 and d.start == 7
    out, _ = redact("number—" + A)
    assert out == "number—[CNIC_1]"
    out, _ = redact(f"PART-{A}-99")
    assert out == "PART-[CNIC_1]-99"
    assert scores(f"applicant-{A}-form") == [50]
    assert scores(f"cnic-{A}-copy") == [80]
    assert scores(f"NADRA ID: 1-{A}") == [80]


def test_en_dash_separators_count_as_standard():
    assert scores("37405–8765432–1") == [80]


def test_spaced_needs_context():
    t = "37405 8765432 1"
    assert scan(t) == []
    assert scores(t, min_score=35) == [35]
    assert scores("CNIC " + t) == [65]
    assert scores("NIC " + t) == [50]


def test_loose_separators_scan_but_parse_strict():
    for t in ("37405-8765432 1", "37405 8765432-1", "37405 - 8765432 - 1"):
        assert scan(t) == []
        assert scores(t, min_score=35) == [35]
        assert scores("CNIC " + t) == [65]


def test_bare_needs_strong_keyword_and_threshold_is_pinned():
    assert scan(A_CAN) == []
    assert scores(A_CAN, min_score=20) == [20]
    assert scores("CNIC: " + A_CAN) == [50]
    assert scan("CNIC: " + A_CAN, min_score=51) == []
    assert scores("nicop " + A_CAN) == [50]
    assert scores("shanakhti card " + A_CAN) == [50]
    assert scores("NADRA " + A_CAN) == [50]
    assert scan("NIC: " + A_CAN) == []  # weak alone = 35
    assert scores("NIC: " + A_CAN, min_score=35) == [35]
    assert scan("NIC nic B-form " + A_CAN) == []  # boosts never stack


# ---------------- lookalike negatives ----------------
@pytest.mark.parametrize("t", [
    "ts 1714000000000",
    "barcode 5901234123457",
    "CNIC 37405876543210",  # 14 digits, never sliced
    "CNIC 37405-8765432-12",
    "valid id " + A_CAN,
    "order number " + A_CAN,
    "Ask Nic about order 1714000000000",
    "replace the NIC; error code 1714000000000",
    "mechanic " + A_CAN,
    "technic " + A_CAN,
    "CNIC 03740-1234567-1",
    "93740-8765432-1",
])
def test_lookalikes_not_detected(t):
    assert scan(t) == []


def test_mechanic_at_window_edge_does_not_boost():
    t = "mechanic" + " " * 32 + A_CAN  # naive slice would start at "nic"
    assert scan(t) == []
    assert scan("mechanic 37405 8765432 1") == []
    assert scores("nic 37405 8765432 1") == [50]  # positive control


def test_window_geometry_is_exact():
    assert scores("cnic" + " " * 31 + A_CAN) == [50]
    assert scan("cnic" + " " * 32 + A_CAN) == []
    assert scores(A_CAN + " " * 31 + "cnic") == [50]
    assert scan(A_CAN + " " * 32 + "cnic") == []


def test_far_keyword_clause_does_not_boost_timestamp():
    t = "Please send your CNIC today." + " " * 40 + "ts=1714000000000"
    assert scan(t) == []


def test_strict_and_allowed_first_digits():
    t = "12345-1234567-1"
    assert len(scan(t)) == 1 and scan(t, strict=True) == []
    t8 = "81101-2345678-9"
    assert len(scan(t8)) == 1
    assert scan(t8, allowed_first_digits=frozenset("1234567")) == []


# ---------------- Urdu ----------------
def test_urdu_digits_offsets_map_to_original():
    t = "میرا " + ur(A) + " ہے"
    (d,) = scan(t)
    assert d.raw_text == ur(A) and t[d.start:d.end] == ur(A)
    assert d.cnic.canonical == A_CAN


def test_urdu_keywords_and_variants():
    num = ur(A_CAN)
    assert scores("شناختی کارڈ " + num) == [50]
    assert scores("قومی شناختی کارڈ " + num) == [50]
    assert scores("نادرا " + num) == [50]
    assert scores("شناخت\u064a \u0643ارڈ " + num) == [50]  # Arabic yeh/kaf
    assert scores("شناخ\u200cتی کارڈ " + num) == [50]  # ZWNJ inside
    assert scores("شناختی کارڈ\u200f " + num) == [50]  # RLM before number
    assert scores("شناختی\u00a0\u00a0کارڈ " + num) == [50]  # NBSPs
    assert scores("ب   فارم 37405 8765432 1") == [50]  # weak + spaced
    assert scores("ب\u00a0\u00a0فارم 37405 8765432 1") == [50]
    assert scan("کتاب فارم 37405 8765432 1") == []  # lookalike prefix


def test_urdu_full_stop_never_touched():
    out, v = redact("میرا شناختی کارڈ نمبر " + A + " ہے۔")
    assert out == "میرا شناختی کارڈ نمبر [CNIC_1] ہے۔"
    out, _ = redact("شناختی کارڈ " + A_CAN + "۔")
    assert out == "شناختی کارڈ [CNIC_1]۔"


# ---------------- redact / restore ----------------
def test_basic_roundtrip_and_dedup_across_formats():
    t = f"CNIC {A} and again {ur(A)}."
    out, v = redact(t)
    assert out == "CNIC [CNIC_1] and again [CNIC_1]."
    assert len(v) == 1
    assert restore(out, v) == f"CNIC {A} and again {A}."  # first-seen form
    assert restore(out, v, fmt="formatted") == f"CNIC {A} and again {A}."
    assert restore(out, v, fmt="canonical") == f"CNIC {A_CAN} and again {A_CAN}."
    out2, v2 = redact(f"{ur(A)} then {A}")
    assert restore(out2, v2) == f"{ur(A)} then {ur(A)}"


def test_two_cnics_get_two_ids():
    out, v = redact(f"CNIC {A} / {B}")
    assert out == "CNIC [CNIC_1] / [CNIC_2]" and len(v) == 2


def test_multi_turn_same_vault_is_consistent():
    _, v = redact(f"CNIC {A}")
    out, _ = redact(f"CNIC {B} and {A}", v)
    assert out == "CNIC [CNIC_2] and [CNIC_1]"


def test_pass1_reserves_before_allocating():
    out, v = redact(f"My CNIC is {A} and here is [CNIC_1]")
    assert out == "My CNIC is [CNIC_2] and here is [CNIC_1]"
    assert restore("[CNIC_2] [CNIC_1]", v) == f"{A} [CNIC_1]"


def test_collision_raises_and_is_atomic():
    _, v = redact(f"CNIC {A}")
    with pytest.raises(PlaceholderCollisionError) as e:
        redact("[CNIC_3] [CNIC_1]", v)
    assert A_CAN not in str(e.value)
    out, _ = redact(f"CNIC {B} and CNIC 35202-1357902-5", v)
    assert out == "CNIC [CNIC_2] and CNIC [CNIC_3]"  # 3 was not reserved


def test_huge_placeholder_id_does_not_crash():
    t = "[CNIC_" + "9" * 5000 + "]"
    out, v = redact(t)
    assert out == t and restore(t, v) == t


def test_idempotence_on_redacted_text():
    out, v = redact(f"CNIC {A}")
    out2, v2 = redact(out)  # fresh vault: nothing to redact
    assert out2 == out and len(v2) == 0
    with pytest.raises(PlaceholderCollisionError):
        redact(out, v)  # same vault: refuses


def test_text_without_cnic_unchanged():
    t = "hello 1714000000000 world"
    assert redact(t)[0] == t


def test_fuzzy_restore_variants():
    _, v = redact(f"CNIC {A}")
    for p in ("[ cnic_1 ]", "[cnic-1]", "[CNIC 1]", "[CNIC_1]", "[ CNIC_01 ]"):
        assert restore(p, v) == A
    assert restore("[[CNIC_1]]", v) == f"[{A}]"  # stray brackets remain
    assert restore("CNIC_1", v) == "CNIC_1"  # brackets required
    assert restore("[CNIC_۱]", v) == "[CNIC_۱]"  # ASCII ids only
    assert restore("[CNIC_9]", v) == "[CNIC_9]"  # unknown id untouched


def test_restore_rejects_unknown_format():
    _, v = redact(f"CNIC {A}")
    with pytest.raises(ValueError):
        restore("[CNIC_1]", v, fmt="masked")


def test_vault_repr_pickle_deepcopy():
    out, v = redact(f"CNIC {A}")
    assert repr(v) == "<RedactionVault [REDACTED] entries=1>"
    assert str(v) == repr(v) and A_CAN not in repr(v)
    with pytest.raises(TypeError):
        pickle.dumps(v)
    v2 = copy.deepcopy(v)
    assert restore(out, v2) == f"CNIC {A}"
    redact(f"CNIC {B}", v2)
    assert len(v2) == 2 and len(v) == 1
    v3 = copy.copy(v)
    assert len(v3) == 1


def test_scan_results_sorted_non_overlapping_and_offsets_valid():
    t = f"x {A} y {B} z"
    ds = scan(t)
    assert [d.start for d in ds] == sorted(d.start for d in ds)
    assert all(t[d.start:d.end] == d.raw_text for d in ds)
    assert ds[0].end <= ds[1].start


# ---------------- Urdu diacritics (marks are not \w) ----------------
def test_urdu_marks_on_keywords():
    assert scores("نادرا\u064f " + A_CAN) == [50]  # trailing mark, then space
    assert scores("شنا\u064eختی کا\u0650رڈ " + A_CAN) == [50]  # marks inside
    assert scores("شناخـتی کارڈ " + A_CAN) == [50]  # tatweel inside
    assert scores("کارڈ".join(["شناختی ", "ـ "]) + A_CAN) == [50]  # trailing tatweel


def test_urdu_keyword_inside_a_vocalized_word_does_not_boost():
    assert scan("ل\u064eنادرا " + A_CAN) == []  # mark before keyword
    assert scan("نادرا\u064fں " + A_CAN) == []  # mark then letter after
    assert scores("ل\u064eنادرا 37405 8765432 1") == []


# ---------------- English keyword variants ----------------
@pytest.mark.parametrize("kw", ["C.N.I.C.", "c.n.i.c", "C.N.I.C", "CNIC", "Nadra"])
def test_en_strong_variants(kw):
    assert scores(f"My {kw} {A_CAN}") == [50]


def test_dotted_cnic_is_lenient_about_a_missing_space():
    # deliberate: a missed boost can leak a number, an extra boost cannot
    assert scores("C.N.I.C.is " + A_CAN) == [50]
    assert scan("abc.n.i.c. " + A_CAN) == []  # but not inside a longer word


@pytest.mark.parametrize("kw", ["B-form", "b form", "bform", "B\u2013form", "B\u00a0form"])
def test_en_b_form_variants_are_weak_keywords(kw):
    assert scan(f"{kw} {A_CAN}") == []  # weak alone: 20 + 15 = 35
    assert scores(f"{kw} 37405 8765432 1") == [50]  # weak + spaced


@pytest.mark.parametrize("w", ["subform", "platform", "reform"])
def test_b_form_lookalikes_do_not_boost(w):
    assert scan(f"{w} 37405 8765432 1") == []


# ---------------- restore / vault ----------------
def test_original_mode_first_seen_hyphenated_then_bare():
    out, v = redact(f"CNIC {A} and CNIC {A_CAN}")
    assert out == "CNIC [CNIC_1] and CNIC [CNIC_1]"
    assert restore(out, v) == f"CNIC {A} and CNIC {A}"
    out, v = redact(f"CNIC {A_CAN} and CNIC {A}")
    assert restore(out, v) == f"CNIC {A_CAN} and CNIC {A_CAN}"


def test_allocation_skips_reserved_ids_with_fast_counter():
    out, v = redact(f"[CNIC_3] CNIC {A} {B} CNIC 35202-1357902-5")
    assert out == "[CNIC_3] CNIC [CNIC_1] [CNIC_2] CNIC [CNIC_4]"
    out2, _ = redact("CNIC 51101-2468013-4", v)
    assert out2 == "CNIC [CNIC_5]"


def test_context_boost_matches_bruteforce():
    import random
    from pakshield.scrubber import CONTEXT_WINDOW, _context_boost

    def naive(start, end, spans):
        best = 0
        for k_start, k_end, boost in spans:
            left = start - CONTEXT_WINDOW <= k_start and k_end <= start
            right = end <= k_start and k_end <= end + CONTEXT_WINDOW
            if (left or right) and boost > best:
                best = boost
        return best

    rng = random.Random(7)
    for _ in range(300):
        spans = sorted(
            (s, s + rng.randint(2, 12), rng.choice([15, 30]))
            for s in (rng.randint(0, 400) for _ in range(rng.randint(0, 40)))
        )
        starts = [k[0] for k in spans]
        for _ in range(20):
            start = rng.randint(0, 400)
            end = start + rng.choice([13, 15, 17])
            assert _context_boost(start, end, spans, starts) == naive(start, end, spans)
