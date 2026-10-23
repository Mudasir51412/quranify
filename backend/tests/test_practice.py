from app.ai.practice import assess_practice
from app.services.transcriber import Recognition


REF = "قُلْ هُوَ ٱللَّهُ أَحَدٌ"


def test_a_stretched_word_recognized_twice_is_not_an_error():
    result = assess_practice(REF, Recognition("قُلْ هُوَ اللَّهُ اللَّهُ أَحَدٌ"))
    assert result.mistakes == {}
    assert result.retry_words == []


def test_split_prolonged_word_requests_a_phrase_retry_instead_of_a_false_error():
    result = assess_practice(REF, Recognition("قُلْ هُوَ اللَّا هُ أَحَدٌ"))
    assert result.mistakes == {}
    assert result.retry_words == [2]


def test_extra_letters_from_a_sustained_sound_are_not_a_confirmed_substitution():
    result = assess_practice(REF, Recognition("قُلْ هُوَ الللللللَّهُ أَحَدٌ"))
    assert result.mistakes == {}
    assert result.retry_words == [2]


def test_restarting_a_long_phrase_clears_corrected_errors():
    reference = "بِسْمِ ٱللَّهِ ٱلرَّحْمَٰنِ ٱلرَّحِيمِ قُلْ هُوَ ٱللَّهُ أَحَدٌ"
    prefix = "بَسْمِ ٱللَّهِ ٱلرَّحْمَٰنِ ٱلرَّحِيمِ قُلْ هُوَ"
    result = assess_practice(reference, Recognition(prefix + " " + reference))
    assert result.mistakes == {}
    assert result.retry_words == []


def test_confirmed_wrong_and_missed_words_remain_distinct():
    wrong = assess_practice(REF, Recognition("قُلْ كِتَابٌ اللَّهُ أَحَدٌ"))
    assert wrong.mistakes[1]["type"] == "incorrect"
    missed = assess_practice(REF, Recognition("قُلْ اللَّهُ أَحَدٌ"))
    assert missed.mistakes[1]["type"] == "skipped"


def test_low_confidence_does_not_turn_into_a_vowel_error():
    result = assess_practice(REF, Recognition("قُلْ هُوَ اللَّهَ أَحَدٌ", ("اللَّهَ",)))
    assert result.mistakes == {}
    assert 2 in result.retry_words


def test_off_passage_or_unreliable_audio_is_a_retry_not_a_row_of_missed_words():
    for recognition in (Recognition("ذهب خالد الى السوق"), Recognition(REF, reliable=False), Recognition("")):
        result = assess_practice(REF, recognition)
        assert result.mistakes == {}
        assert result.retry_words == [0, 1, 2, 3]


def test_consistent_vowel_error_is_still_reported():
    result = assess_practice(REF, Recognition("قُلْ هُوَ اللَّهَ أَحَدٌ"))
    assert result.retry_words == []
    assert result.mistakes[2]["reason"] == "harakat"


def test_unvocalized_self_correction_requests_retry_instead_of_reasserting_the_old_error():
    result = assess_practice(REF, Recognition("قُلْ هُوَ اللَّهَ الله أَحَدٌ"))
    assert result.mistakes == {}
    assert result.retry_words == [2]
