"""Al-Fatiha: retain actual mistakes while allowing only narrow ASR repairs."""
from app.ai.practice import assess_practice
from app.services.transcriber import Recognition


REF = "إِيَّاكَ نَعْبُدُ وَإِيَّاكَ نَسْتَعِينُ"


def test_uncertainty_on_one_word_does_not_hide_an_omission_elsewhere():
    result = assess_practice(REF, Recognition("إِيَّاكَ وَإِيَّاكَ نَسْتَعِينُ", ("نَسْتَعِينُ",)))
    assert result.states[1] == "skipped"
    assert result.mistakes[1]["type"] == "skipped"
    assert result.states[3] == "retry"


def test_uncertainty_on_one_word_does_not_hide_a_wrong_vowel_elsewhere():
    result = assess_practice(REF, Recognition("إِيَّاكَ نَعْبِدُ وَإِيَّاكَ نَسْتَعِينُ", ("نَسْتَعِينُ",)))
    assert result.states[1] == "incorrect"
    assert result.mistakes[1]["reason"] == "harakat"
    assert result.states[3] == "retry"


def test_a_changed_consonant_is_not_presented_as_correct():
    reference = "ٱهْدِنَا ٱلصِّرَٰطَ ٱلْمُسْتَقِيمَ"
    result = assess_practice(reference, Recognition("ٱهْدِنَا ٱلصِّرَٰطَ ٱلْمُسْتَقِينَمَ"))
    assert result.states[2] == "retry"


def test_omitting_a_repeated_fatiha_word_still_counts_as_missed():
    for index in range(4):
        words = REF.split()
        result = assess_practice(REF, Recognition(" ".join(words[:index] + words[index + 1:])))
        assert "skipped" in result.states


def test_partial_diacritics_and_tatweel_keep_the_previous_comparison_behavior():
    reference = "ٱهْدِنَا ٱلصِّرَٰطَ ٱلْمُسْتَقِيمَ"
    result = assess_practice(reference, Recognition("اهدِنَـــا الصِّرَاطَ المُستَقِيمَ"))
    assert result.states == ["matched", "matched", "matched"]


def test_long_alif_mark_placement_does_not_create_a_vowel_error():
    result = assess_practice("وَلَا", Recognition("ولاَ"))
    assert result.mistakes == {}


def test_a_clearly_substituted_word_is_still_wrong():
    result = assess_practice(REF, Recognition("إِيَّاكَ كِتَابٌ وَإِيَّاكَ نَسْتَعِينُ"))
    assert result.mistakes[1]["type"] == "incorrect"


def test_an_isolated_final_vowel_difference_is_retry_not_correct():
    result = assess_practice(REF, Recognition("إِيَّاكَ نَعْبُدُ وَإِيَّاكَ نَسْتَعِينَ"))
    assert result.states[3] == "retry"
    assert result.states[:3] == ["matched", "matched", "matched"]


def test_a_missing_word_is_not_hidden_by_a_final_vowel_retry():
    result = assess_practice(REF, Recognition("إِيَّاكَ وَإِيَّاكَ نَسْتَعِينَ"))
    assert result.mistakes[1]["type"] == "skipped"
    assert result.states[3] == "retry"


def test_every_single_word_omission_in_fatiha_remains_visible():
    from app.ai.reference import load_reference
    for entry in load_reference()[1].values():
        words = entry["text"].split()
        for index in range(len(words)):
            heard = " ".join(words[:index] + words[index + 1:])
            result = assess_practice(entry["text"], Recognition(heard))
            assert index in result.mistakes, (words, index, result.states)


def test_shadda_difference_reports_the_reason_when_vowels_are_identical():
    result = assess_practice("ٱلرَّحِيمِ", Recognition("الرَحِيمِ"))
    error = result.mistakes[0]["harakat_errors"][0]
    assert error["expected_vowel"] == error["heard_vowel"] == "fatha"
    assert error["expected_shadda"] is True
    assert error["heard_shadda"] is False
