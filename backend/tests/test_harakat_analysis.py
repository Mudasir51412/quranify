"""Cases 25-36 from report §5.1.3 — all passed there; case 33 semantics
strengthened: unvocalized = 0 errors BUT uncertain > 0 (not proof of correct)."""
from app.ai.harakat import compare_harakat, compare_word_harakat


def test_25_correct_vowels():
    errs, unc = compare_word_harakat("كَتَبَ", "كَتَبَ")
    assert errs == [] and unc == 0

def test_26_fatha_error():
    errs, _ = compare_word_harakat("كَتَبَ", "كِتَبَ")
    assert len(errs) == 1 and errs[0].expected_vowel == "fatha" and errs[0].heard_vowel == "kasra"

def test_27_kasra_error():
    errs, _ = compare_word_harakat("كِتَبَ", "كَتَبَ")
    assert len(errs) == 1 and errs[0].expected_vowel == "kasra"

def test_28_damma_error():
    errs, _ = compare_word_harakat("كُتَبَ", "كَتَبَ")
    assert len(errs) == 1 and errs[0].expected_vowel == "damma"

def test_29_empty_matched_set():
    errs, unc = compare_harakat([], [])
    assert errs == [] and unc == 0

def test_30_multiple_correct_words():
    errs, unc = compare_harakat(["بِسْمِ", "ٱللَّهِ"], ["بِسْمِ", "ٱللَّهِ"])
    assert errs == [] and unc == 0

def test_31_mixed_one_error():
    errs, _ = compare_harakat(["بِسْمِ", "ٱللَّهِ"], ["بَسْمِ", "ٱللَّهِ"])
    assert len(errs) == 1

def test_32_out_of_bounds_index_safe():
    errs, _ = compare_harakat(["كَتَبَ"], ["كَتَبَ"], skipped_indices={999})
    assert errs == []

def test_33_unvocalized_is_uncertain_not_correct():
    errs, unc = compare_word_harakat("كَتَبَ", "كتب")
    assert errs == []
    assert unc > 0  # insufficient evidence must be visible to caller

def test_34_tanween_mismatch():
    errs, _ = compare_word_harakat("كِتَابٌ", "كِتَابٍ")
    assert len(errs) == 1 and errs[0].expected_vowel == "damma" and errs[0].heard_vowel == "kasra"

def test_35_shadda_omission():
    errs, _ = compare_word_harakat("رَبِّ", "رَبِ")
    assert len(errs) == 1 and errs[0].expected_shadda is True and errs[0].heard_shadda is False

def test_36_skipped_word_excluded():
    errs, _ = compare_harakat(
        ["بِسْمِ", "ٱللَّهِ", "ٱلرَّحْمَٰنِ"],
        ["بِسْمِ", "ٱللَّاهِ", "ٱلرَّحْمَٰنِ"],
        skipped_indices={1},
    )
    assert errs == []
