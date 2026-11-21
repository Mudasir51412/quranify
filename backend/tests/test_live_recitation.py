"""Live tracking: no false tail skips, stability, corrections, and streaming auth."""
import uuid
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai.guided import GuidedRecitation
from app.ai.live import LiveRecitation, StableWords
from app.ai.recitation_difficulty import RecitationDifficulty
from app.ai.reference import load_reference
from app.db import Base, get_db
from app.main import app
from app.routers.analyze import get_transcriber
from app.routers.live import AudioBuffer
from app.services.fast_transcriber import FasterWhisperTranscriber
from app.services.transcriber import SpokenWord


def tracker():
    return LiveRecitation({1: "قُلْ هُوَ ٱللَّهُ أَحَدٌ", 2: "ٱللَّهُ ٱلصَّمَدُ"})


def test_annotations_preserve_raw_indices_and_targeted_retry():
    guided = GuidedRecitation({1: '۞ قل ۚ هو ۩ احد'})
    guided.accept(['قل', 'هو', 'احد'], final=True)
    assert guided.completed and not guided.mistakes
    assert [w['word_index'] for w in guided.snapshot()['words']] == [1, 3, 5]
    guided = GuidedRecitation({1: '۞ قل ۚ هو ۩ احد'})
    guided.accept(['قل', 'احد'], final=True)
    guided.begin_segment(ayah=1, word_index=3)
    guided.accept(['هو'], final=True)
    assert guided.completed and guided.retry_result == 'correct'


@pytest.mark.parametrize(("variant", "accepted"), [
    ("المغضووب", {RecitationDifficulty.BEGINNER, RecitationDifficulty.INTERMEDIATE}),
    ("المغغضوب", {RecitationDifficulty.BEGINNER}),
])
def test_guided_difficulty_differs_on_the_same_stable_words(variant, accepted):
    for level in RecitationDifficulty:
        guided = GuidedRecitation({1: "غَيْرِ ٱلْمَغْضُوبِ عَلَيْهِمْ"}, difficulty=level)
        guided.accept([SpokenWord("غير", 0.02, 0.2), SpokenWord(variant, 0.3, 0.6),
                       SpokenWord("عليهم", 0.7, 1.1)], final=True)
        assert guided.completed is (level in accepted)
        assert guided.mistakes == {}
        if level == RecitationDifficulty.INTERMEDIATE and level not in accepted:
            assert guided.snapshot()["repeat_word"] == 1
            guided.accept(["المغضوب", "عليهم"], final=True)
            assert guided.completed
            assert guided.snapshot()["repeat_word"] is None


def test_intermediate_boundary_variant_requires_independent_repeat_and_an_anchor():
    guided = GuidedRecitation({1: "رَبِّ ٱلْعَٰلَمِينَ"}, difficulty=RecitationDifficulty.INTERMEDIATE)
    candidate = SpokenWord("العالميين", 0.3, 0.8)
    guided.accept([SpokenWord("رب", 0.02, 0.22), candidate], final=True)
    assert guided.snapshot()["repeat_word"] == 1
    assert guided.states == {0: "matched"}
    guided.accept([candidate], final=True)  # Retime/reprocessing of the same sound.
    assert not guided.completed
    guided.begin_segment(ayah=1, replay_ayah=True)
    guided.accept([SpokenWord("العالميين", 0.1, 0.55)], final=True)
    assert guided.completed


@pytest.mark.parametrize("level", list(RecitationDifficulty))
def test_guided_targeted_variant_depends_on_difficulty(level):
    guided = GuidedRecitation({1: "غَيْرِ ٱلْمَغْضُوبِ عَلَيْهِمْ"}, difficulty=level)
    guided.accept(["غير", "عليهم"])
    assert guided.mistakes[1]["type"] == "skipped"
    for reliability in (True, False, True, True):
        guided.begin_segment(ayah=1, word_index=1)
        guided.accept([SpokenWord("المغضووب", 0.03, 0.6, reliable=reliability)], final=True)
        if level == RecitationDifficulty.EXPERT:
            assert guided.retry_result == "incorrect"
        elif guided.mistakes[1]["corrected"]:
            assert guided.retry_result == "correct"
            assert (reliability and not guided.blocked)
            break
        else:
            assert level == RecitationDifficulty.INTERMEDIATE
            assert guided.retry_result == "repeat"
    assert guided.mistakes[1]["corrected"] is (level != RecitationDifficulty.EXPERT)
    assert guided.mistakes[1]["type"] == "skipped"


def test_beginner_does_not_credit_weak_or_known_distinct_variants():
    for candidate, vocabulary in (
        (SpokenWord("المغضووب", 0.3, 0.6, reliable=False), None),
        (SpokenWord("المغضووب", 0.3, 0.6), {"المغضووب"}),
    ):
        guided = GuidedRecitation({1: "غير المغضوب عليهم"},
                                  difficulty=RecitationDifficulty.BEGINNER, vocabulary=vocabulary)
        guided.accept([SpokenWord("غير", 0.02, 0.2), candidate,
                       SpokenWord("عليهم", 0.7, 1.1)], final=True)
        assert guided.states == {0: "matched"}
        assert not guided.mistakes


def test_intermediate_exact_repetition_replaces_a_pending_close_word():
    guided = GuidedRecitation({1: "غير المغضوب عليهم"},
                              difficulty=RecitationDifficulty.INTERMEDIATE)
    guided.accept(["غير", "المغغضوب"])
    assert guided.snapshot()["repeat_word"] == 1
    guided.accept(["المغضوب", "عليهم"])
    assert guided.completed
    assert not guided.mistakes


@pytest.mark.parametrize("level", list(RecitationDifficulty))
def test_short_words_and_clear_substitutions_follow_the_existing_gate(level):
    guided = GuidedRecitation({1: "قُلْ هُوَ أَحَدٌ"}, difficulty=level)
    guided.accept(["قُلْ", "كتاب", "أَحَدٌ"])
    assert guided.mistakes[1]["type"] == "incorrect"
    guided.begin_segment(ayah=1, word_index=1)
    guided.accept(["ووهو"], final=True)
    assert guided.retry_result == "incorrect"
    assert not guided.mistakes[1]["corrected"]


def test_guided_correction_gate_ignores_future_speech_and_isolates_each_retry():
    guided = GuidedRecitation({1: "قُلْ هُوَ أَحَدٌ", 2: "ٱللَّهُ ٱلصَّمَدُ"})
    guided.accept(["اللَّهُ", "الصَّمَدُ"], final=True)
    assert guided.snapshot()["scored_words"] == 0
    guided.accept(["قُلْ", "أَحَدٌ", "اللَّهُ", "الصَّمَدُ"])
    assert guided.snapshot()["current_ayah"] == 1
    assert guided.states == {0: "matched", 1: "skipped"}
    guided.accept(["هُوَ", "أَحَدٌ", "اللَّهُ", "الصَّمَدُ"], final=True)
    assert not guided.mistakes[1]["corrected"]
    with pytest.raises(ValueError, match="no longer active"):
        guided.begin_segment(ayah=2, word_index=0)
    guided.begin_segment(ayah=1, word_index=1)
    guided.accept([SpokenWord("هُوُ", 0, 0.4, pronunciation_evidence=True)], final=True)
    assert guided.retry_result == "incorrect"
    assert guided.mistakes[1]["type"] == "skipped"
    guided.begin_segment(ayah=1, word_index=1)
    guided.accept(["هُوَ", "الصَّمَدُ"], final=True)
    assert guided.retry_result == "incorrect"
    assert not guided.mistakes[1]["corrected"]
    guided.begin_segment(ayah=1, word_index=1)
    guided.accept(["هُوَ"], final=True)
    assert guided.retry_result == "correct"
    assert guided.mistakes[1]["corrected"]
    assert guided.snapshot()["current_word"] == 2
    with pytest.raises(ValueError, match="flagged word"):
        guided.begin_segment(ayah=1, word_index=1)
    guided.accept(["أَحَدٌ", "اللَّهُ", "الصَّمَدُ"], final=True)
    assert guided.snapshot()["current_ayah"] == 1
    guided.begin_segment()
    guided.accept(["أَحَدٌ", "اللَّهُ", "الصَّمَدُ"], final=True)
    assert guided.snapshot()["completed"]


def test_guided_keeps_ambiguous_word_unmarked_and_can_restart_just_this_ayah():
    guided = GuidedRecitation({1: "قُلْ هُوَ أَحَدٌ", 2: "ٱللَّهُ ٱلصَّمَدُ"})
    guided.accept(["قُلْ", SpokenWord("كتاب", 0.2, 0.4, reliable=False),
                   SpokenWord("أَحَدٌ", 0.5, 0.8)], final=True)
    assert guided.states == {0: "matched"}
    assert not guided.mistakes
    guided.begin_segment(ayah=1, replay_ayah=True)
    guided.accept(["قَلْ", "هو", "أَحَدْ", "الله"], final=True)
    assert guided.snapshot()["current_ayah"] == 2
    assert guided.states == {i: "matched" for i in range(4)}


def test_guided_finishes_single_word_ayah_only_after_supported_correction():
    guided = GuidedRecitation({1: "قُلْ", 2: "هُوَ"})
    guided.accept([SpokenWord("قَلْ", 0, 0.3, pronunciation_evidence=True),
                   SpokenWord("هُوَ", 0.4, 0.7)])
    assert guided.snapshot()["current_ayah"] == 1
    assert guided.states == {0: "incorrect"}
    guided.begin_segment(ayah=1, word_index=0)
    guided.accept([SpokenWord("قُلْ", 0, 0.3, pronunciation_evidence=True)], final=True)
    assert guided.snapshot()["current_ayah"] == 2
    assert not guided.snapshot()["completed"]
    guided.begin_segment()
    guided.accept(["هو"], final=True)
    assert guided.snapshot()["completed"]


def test_guided_flags_contiguous_wrong_final_word_with_no_future_credit():
    guided = GuidedRecitation({1: "قُلْ هُوَ", 2: "ٱللَّهُ ٱلصَّمَدُ"})
    guided.accept([SpokenWord("قُلْ", 0.06, 0.28)])
    guided.accept([], final=True)
    assert not guided.mistakes  # Quiet alone does not score the tail.
    guided.accept([SpokenWord("هُمْ", 0.44, 0.80)])
    assert not guided.mistakes
    guided.accept([], final=True)
    assert guided.mistakes[1]["type"] == "incorrect"
    assert guided.snapshot()["current_ayah"] == 1
    guided.accept(["اللَّهُ", "الصَّمَدُ"], final=True)
    assert max(guided.states) == 1
    guided.begin_segment(ayah=1, word_index=1)
    guided.accept(["هُوَ"], final=True)
    assert guided.snapshot()["current_ayah"] == 2
    assert max(guided.states) == 1


def test_guided_single_word_wrong_final_needs_independent_boundary_or_reread():
    guided = GuidedRecitation({1: "قُلْ", 2: "ٱللَّهُ ٱلصَّمَدُ"})
    guided.accept([SpokenWord("كُلْ", 0.08, 0.35)], final=True)
    assert guided.states == {}  # A standalone unknown token is unresolved.
    guided.begin_segment(ayah=1, replay_ayah=True)
    guided.accept([SpokenWord("كُلْ", 0.05, 0.28), SpokenWord("اللَّهُ", 0.3, 0.6),
                   SpokenWord("الصَّمَدُ", 0.67, 1.02)], final=True)
    assert guided.states == {0: "incorrect"}
    assert guided.snapshot()["current_ayah"] == 1
    guided.begin_segment(ayah=1, word_index=0)
    guided.accept(["قل"], final=True)
    assert guided.states == {0: "matched"}
    assert guided.snapshot()["current_ayah"] == 2
    assert guided.mistakes[0]["corrected"]


def test_guided_short_ayah_next_pair_can_anchor_a_last_miss_but_gets_no_credit():
    guided = GuidedRecitation({1: "قُلْ هُوَ", 2: "ٱللَّهُ ٱلصَّمَدُ"})
    guided.accept(["قُلْ"])
    guided.accept(["اللَّهُ"])
    assert guided.states == {0: "matched"}
    guided.accept(["الصَّمَدُ"])
    assert guided.states == {0: "matched", 1: "skipped"}
    assert guided.snapshot()["current_ayah"] == 1


def test_fatiha_forward_pair_recovers_from_a_disproved_far_anchor():
    live = LiveRecitation({a: row["text"] for a, row in load_reference()[1].items()})
    live.accept(["بِسْمِ", "اللَّهِ"])
    # An isolated word from farther ahead cannot establish progress. When
    # the following decode supplies ayahs 2 and 3, it must also not block them.
    live.accept(["رَبِّ"])
    assert live.cursor == 2
    for words in (["الْحَمْدُ", "لِلَّهِ"], ["رَبِّ", "الْعَالَمِينَ"],
                  ["الرَّحْمَانِ", "الرَّحِيمِ"]):
        live.accept(words)
    assert live.cursor == 10
    assert live.snapshot()["current_ayah"] == 4
    assert live.snapshot()["confirmed_words"] == 8
    assert [live.states[i] for i in (2, 3)] == ["unconfirmed", "unconfirmed"]
    assert live.mistakes == {}


def test_fatiha_recovery_checks_past_a_queued_restart_and_unclear_third_ayah():
    ref = {a: row["text"] for a, row in load_reference()[1].items()}
    live = LiveRecitation(ref)
    live.accept(ref[1].split() + ref[2].split())
    for word in ["رحيم", *ref[2].split(), "الرحمن", "الرجيم", "حين"]:
        live.accept([word])
    assert live.cursor == 8
    live.accept(ref[4].split())
    assert live.cursor == 13
    assert live.states[9] == "unconfirmed"
    assert live.mistakes == {}


def test_a_vocalization_change_cannot_block_stable_words_after_it():
    stable = StableWords()
    first = [SpokenWord("الرَّحْمَانِ", 0, 0.4), SpokenWord("الرَّحِيمِ", 0.4, 0.8)]
    second = [SpokenWord("الرَّحْمَانَ", 0, 0.4, reliable=False), first[1]]
    assert stable.update(first) == []
    committed = stable.update(second)
    assert len(committed) == 2
    live = LiveRecitation({3: "ٱلرَّحْمَٰنِ ٱلرَّحِيمِ"})
    live.accept(committed)
    assert live.cursor == 2
    assert live.mistakes == {}
    assert live.uncertain == set()


def test_spelling_agreement_with_two_unreliable_observations_stays_uncertain():
    stable = StableWords()
    assert stable.update([SpokenWord("قَلْ", 0, 0.4, reliable=False)]) == []
    committed = stable.update([SpokenWord("قل", 0, 0.4, reliable=False)])
    live = tracker()
    live.accept(committed)
    assert live.cursor == 1
    assert live.uncertain == {0}
    assert live.mistakes == {}
    assert live.snapshot()["confirmed_words"] == 0
    assert live.snapshot()["matched_words"] == 0


def test_borderline_requires_segment_quality_and_two_supported_hypotheses(monkeypatch):
    model = FasterWhisperTranscriber("unused")
    moderate = SimpleNamespace(word="قل", probability=0.60, start=0.1, end=0.3)
    monkeypatch.setattr(model, "_segments", lambda *_: [
        SimpleNamespace(words=[moderate], avg_logprob=-0.6, no_speech_prob=0.1),
        SimpleNamespace(words=[moderate], avg_logprob=-0.6, no_speech_prob=0.8),
    ])
    supported, noise = model.transcribe_words(np.ones(16000, dtype=np.float32))
    assert supported.borderline and not supported.reliable
    assert not noise.borderline and not noise.reliable
    stable = StableWords()
    stable.update([noise])
    assert not stable.update([supported])[0].borderline
    stable = StableWords()
    stable.update([supported])
    hit = stable.update([supported])[0]
    assert hit.borderline and hit.stable and not hit.reliable


def test_fatiha_unvocalized_exact_words_and_known_spelling_advance_cleanly():
    live = LiveRecitation({3: load_reference()[1][3]["text"]})
    live.accept(["الرحمن"])
    assert live.cursor == 1
    live.accept(["الرحيم"])
    assert live.snapshot()["completed"]
    assert live.uncertain == set()


def test_optional_opening_does_not_jump_past_the_selected_fatiha_ayah():
    live = LiveRecitation({a: row["text"] for a, row in load_reference()[1].items() if a >= 2})
    for word in ["بسم", "الله", "الرحمن", "الرحيم"]:
        live.accept([word])
    assert live.cursor == 0
    live.accept(["الحمد", "لله", "رب", "العالمين", "الرحمن", "الرحيم"])
    assert live.snapshot()["current_ayah"] == 4
    assert not live.mistakes


def test_pause_and_unread_tail_are_not_mistakes():
    live = tracker()
    live.accept(["قُلْ"])
    live.accept([])
    live.accept([], final=True)
    assert live.snapshot()["scored_words"] == 1
    assert live.snapshot()["mistakes"] == []


def test_skip_is_revealed_only_after_a_later_anchor_then_correction_hides_it():
    live = tracker()
    live.accept(["قُلْ"])
    assert not live.mistakes
    live.accept(["اللَّهُ"])
    assert live.states[1] == "skipped"
    assert live.cursor == 3
    live.accept(["هُوَ"])
    assert live.states[1] == "matched"
    assert live.mistakes[1]["corrected"] is True
    assert live.cursor == 3  # Revisiting doesn't rewind the forward position.
    live.accept(["أَحَدٌ", "اللَّهُ", "الصَّمَدُ"])
    assert live.snapshot()["completed"] is True


def test_wrong_word_needs_following_anchor_and_can_be_corrected():
    live = tracker()
    live.accept(["قُلْ", "كتاب"])
    assert not live.mistakes
    live.accept(["اللَّهُ"])
    assert live.states[1] == "incorrect"
    live.accept(["هُوَ"])
    assert live.mistakes[1]["corrected"]


@pytest.mark.parametrize(("reference", "wrong", "right"), [
    ("لَمْ يَلِدْ وَلَمْ يُولَدْ", "وَلَن", "وَلَمْ"),
    ("رَبِّ ٱلرَّحِيمِ يَوْمِ", "الرَّجِيم", "الرَّحِيمِ"),
])
def test_stable_close_spelling_is_incorrect_and_repeating_target_corrects_it(
    reference, wrong, right,
):
    tokens = reference.split()
    index = len(tokens) - 2
    live = LiveRecitation({1: reference})
    live.accept(tokens[:index])
    stable = StableWords()
    words = [SpokenWord(wrong, 0.2, 0.5), SpokenWord(tokens[-1], 0.52, 0.8)]
    assert stable.update(words) == []
    assert live.snapshot()["mistakes"] == []
    live.accept(stable.update(words))
    assert live.states[index] == "incorrect"
    assert live.mistakes[index]["reason"] == "word"
    live.accept([right])
    assert live.states[index] == "matched"
    assert live.mistakes[index]["corrected"] is True


def test_wrong_vowel_is_not_cleared_without_vowel_evidence():
    live = tracker()
    live.accept([SpokenWord("قَلْ", 0, 0.3, pronunciation_evidence=True)])
    assert live.states[0] == "incorrect"
    live.accept(["قل"])
    assert live.states[0] == "incorrect"
    live.accept(["قُلْ"])
    assert live.states[0] == "incorrect"
    live.accept([SpokenWord("قُلْ", 1, 1.3, pronunciation_evidence=True)])
    assert live.states[0] == "matched"
    assert live.mistakes[0]["corrected"]


def test_reference_benchmark_vowel_mismatch_does_not_penalize_the_written_word():
    live = tracker()
    live.accept(["قُلْ", "هُوَ", "اللَّهُ", "أَحَدٌ", "اللَّهَ", "الصَّمَدُ"])
    result = live.snapshot()
    assert result["completed"]
    assert not result["mistakes"]
    assert result["words"][4] == {
        "ayah": 2, "word_index": 0, "state": "matched", "uncertain": False}


def test_a_pausal_ending_is_not_a_pronunciation_error():
    live = tracker()
    live.accept(["قُلْ", "هُوَ", "اللَّهُ",
                 SpokenWord("أَحَدْ", 1, 1.5, pronunciation_evidence=True)])
    assert live.cursor == 4
    assert live.mistakes == {}
    live = LiveRecitation({1: "رَحْمَةٌ"})
    live.accept(["رَحْمَهْ"])
    assert live.snapshot()["completed"]
    assert live.snapshot()["matched_words"] == 1
    assert not live.uncertain
    assert live.mistakes == {}


def test_low_confidence_replacement_leaves_uncertainty_and_keeps_tracking():
    live = tracker()
    live.accept(["قُلْ", SpokenWord("كتاب", 0.4, 0.6, reliable=False), "اللَّهُ"])
    assert live.cursor == 3
    assert live.mistakes == {}
    assert live.states[1] == "unconfirmed"
    live.accept(["هُوَ"])
    assert live.states[1] == "matched"
    assert live.cursor == 3


def test_connected_fatiha_ending_recognizes_the_noun_without_guessing_the_particle():
    ayah = load_reference()[1][7]["text"]
    for ending in (["وَلِلضَّالِّينَ"], ["وَلِلضَّى", "الضَّالِّينَ"]):
        live = LiveRecitation({7: ayah})
        live.accept(ayah.split()[:-2])
        live.accept(ending)
        assert live.snapshot()["completed"]
        assert live.states[7] == "unconfirmed"
        assert live.states[8] == "matched"
        assert live.mistakes == {}

    # The previous window may have already committed the particle before a
    # later decode re-segments both as a single token.
    live = LiveRecitation({7: ayah})
    live.accept(ayah.split()[:-1])
    live.accept(["وَلِلضَّالِّينَ", "كتاب"])
    result = live.snapshot()
    assert result["completed"]
    assert result["matched_words"] == 9
    assert result["status"] == "ok"
    assert result["unconfirmed_words"] == 0
    assert result["mistakes"] == []


def test_whole_prior_ayah_replay_corrects_without_skipping_forward_shared_word():
    live = LiveRecitation({
        1: "قُلْ هُوَ ٱللَّهُ أَحَدٌ", 2: "ٱلرَّحْمَٰنُ ٱللَّهُ غَفُورٌ",
    })
    live.accept(["قُلْ", "اللَّهُ", "أَحَدٌ"])
    assert live.cursor == 4
    for word in ["قُلْ", "هُوَ", "اللَّهُ", "أَحَدٌ"]:
        live.accept([word])
        assert live.cursor == 4
    assert live.mistakes[1]["corrected"]
    assert list(live.mistakes) == [1]
    live.accept(["الرَّحْمَٰنُ", "اللَّهُ", "غَفُورٌ"])
    assert live.snapshot()["completed"]


def test_ayah_replay_can_share_its_opening_word_with_forward_position():
    live = LiveRecitation({1: "قُلْ هُوَ أَحَدٌ", 2: "قُلْ ٱللَّهُ"})
    live.accept(["قُلْ", "هُوَ", SpokenWord("أَحُدٌ", 1, 1.2, pronunciation_evidence=True)])
    assert live.states[2] == "incorrect"
    live.accept(["قُلْ", "هُوَ", SpokenWord("أَحَدٌ", 2, 2.2, pronunciation_evidence=True)])
    assert live.cursor == 3
    assert live.mistakes[2]["corrected"]
    live.accept(["قُلْ", "اللَّهُ"])
    assert live.snapshot()["completed"]


def test_a_forward_pair_preempts_an_incomplete_replay_with_a_shared_word():
    live = LiveRecitation({1: "قرأ ثم قال هناك", 2: "قال هنا"})
    live.accept(["قرأ", "ثم", "قال", "هناك"])
    live.accept(["قرأ", "ثم"])
    assert live.cursor == 4
    live.accept(["قال", "هنا"])
    assert live.snapshot()["completed"]
    assert live.mistakes == {}


def test_correction_after_crossing_an_ayah_and_correct_repetitions():
    live = tracker()
    live.accept(["قُلْ", "اللَّهُ", "أَحَدٌ", "اللَّهُ"])
    assert live.cursor == 5
    live.accept(["اللَّهُ"])
    assert live.cursor == 5
    live.accept(["هُوَ"])
    assert live.mistakes[1]["corrected"]


def test_extra_speech_does_not_stall_following_words():
    live = tracker()
    live.accept(["قُلْ", "كتاب", "هُوَ", "اللَّهُ"])
    assert live.cursor == 3
    assert not live.mistakes


def test_split_arabic_tokens_do_not_stall_the_following_ayah():
    live = LiveRecitation({3: "لَمْ يَلِدْ وَلَمْ يُولَدْ", 4: "وَلَمْ يَكُن لَّهُۥ كُفُوًا أَحَدٌ"})
    live.accept(["لَمْ", "يَلِدْ", "وَلَا", "مْ", "يُولَدْ", "وَلَمْ", "يَكُن", "لَّهُ", "كُفُوًا", "أَحَدٌ"])
    assert live.snapshot()["completed"] is True
    assert live.snapshot()["uncertain_words"] >= 1
    assert live.mistakes == {}


def test_single_decode_flushed_during_pause_cannot_confirm_a_substitution():
    live = LiveRecitation({3: "لَمْ يَلِدْ وَلَمْ يُولَدْ"})
    live.accept(["لَمْ", "يَلِدْ"])
    stable = StableWords()
    assert stable.update([SpokenWord("وَلَن", 0.6, 0.9),
                          SpokenWord("يُولَدْ", 0.95, 1.5)]) == []
    live.accept(stable.flush(), final=True)
    result = live.snapshot()
    assert result["completed"]
    assert result["mistakes"] == []
    assert result["words"][2]["state"] == "unconfirmed"


def test_overlapping_substitution_and_anchor_leave_the_word_unscored():
    live = tracker()
    live.accept(["قُلْ", SpokenWord("كتاب", 0.3, 0.8), SpokenWord("اللَّهُ", 0.6, 0.75)])
    assert live.states[1] == "unconfirmed"
    assert live.mistakes == {}


def test_exact_split_tokens_are_joined_without_a_false_skip():
    live = LiveRecitation({1: "الحمد لله"})
    live.accept(["ال", "حمد", "لله"])
    assert live.snapshot()["completed"] is True
    assert not live.mistakes


def test_long_jump_requires_two_consecutive_anchors():
    live = tracker()
    live.accept(["الصَّمَدُ"])
    assert live.cursor == 0
    assert not live.mistakes


def test_hypotheses_must_agree_and_old_audio_is_not_counted_twice():
    stable = StableWords()
    first = [SpokenWord("قُلْ", 0, 0.3)]
    assert stable.update(first) == []
    assert stable.update([SpokenWord("كُلْ", 0, 0.3)]) == []
    assert stable.update(first) == []
    assert stable.update(first) == first
    assert stable.update(first) == []
    tail = SpokenWord("هُوَ", 0.4, 0.7)
    assert stable.update(first + [tail]) == []
    assert stable.update(first + [tail], final=True) == [tail]


def test_changed_end_timestamp_does_not_repeat_a_committed_word():
    stable = StableWords()
    first = [SpokenWord("قُلْ", 0, 0.3)]
    stable.update(first)
    stable.update(first)
    grown = [SpokenWord("قُلْ", 0, 0.45), SpokenWord("هُوَ", 0.5, 0.8)]
    assert stable.update(grown) == []
    assert stable.update(grown) == [grown[1]]


def test_window_retiming_does_not_drop_a_new_overlapping_word():
    stable = StableWords()
    first = [SpokenWord("قُلْ", 0.0, 0.5)]
    stable.update(first)
    stable.update(first)
    # A rolling decode moves the next word's start earlier than the previous
    # decode's end. Its identity and end still establish a new occurrence.
    next_word = SpokenWord("هُوَ", 0.3, 0.8)
    assert stable.update(first + [next_word]) == []
    assert stable.update(first + [next_word]) == [next_word]


def test_repeated_word_at_a_new_audio_position_is_not_deduplicated():
    stable = StableWords()
    first = [SpokenWord("اللَّهُ", 0.0, 0.5)]
    stable.update(first)
    stable.update(first)
    repeated = SpokenWord("اللَّهُ", 0.6, 1.1)
    stable.update(first + [repeated])
    assert stable.update(first + [repeated]) == [repeated]


def test_retiring_a_long_pause_preserves_newly_received_audio():
    buffer = AudioBuffer()
    buffer.pcm = bytearray(16000 * 10 * 2)
    buffer.received = 16000 * 10
    buffer.retire_silence(16000 * 8)
    assert buffer.offset == 16000 * 7.5
    assert len(buffer.pcm) == 16000 * 2.5 * 2


def test_buffer_keeps_unprocessed_audio_and_rejects_overrun():
    buffer = AudioBuffer()
    frame = np.ones(8000, dtype="<i2").tobytes()
    for _ in range(20):
        buffer.append(frame)
    buffer.retire(5)
    assert buffer.offset == 64000
    assert len(buffer.pcm) == (160000 - 64000) * 2
    with pytest.raises(ValueError):
        buffer.append(b"odd")
    for _ in range(28):
        buffer.append(frame)
    with pytest.raises(ValueError, match="cannot keep up"):
        buffer.append(frame)


class StreamingFake:
    device = "cpu"

    def __init__(self):
        self.calls = 0

    def prepare_stream(self):
        return self.device

    def transcribe_words(self, audio):
        self.calls += 1
        # Skip hu, then say it later as a correction. Timing is absolute in
        # this short fixture; real recognition returns window-relative times.
        words = [SpokenWord("قُلْ", 0.05, 0.2), SpokenWord("اللَّهُ", 0.25, 0.45)]
        if len(audio) >= 16000:
            words.append(SpokenWord("هُوَ", 0.55, 0.85))
        return words


@pytest.fixture
def streaming_client():
    previous = dict(app.dependency_overrides)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    factory = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)

    def db_override():
        with factory() as db:
            yield db

    fake = StreamingFake()
    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[get_transcriber] = lambda: fake
    with TestClient(app) as client:
        yield client, fake
    app.dependency_overrides.clear()
    app.dependency_overrides.update(previous)
    engine.dispose()


def register(client):
    response = client.post("/auth/register", json={
        "email": f"live-{uuid.uuid4()}@test.local", "password": "secret123"})
    assert response.status_code == 201
    return response.json()["token"]


def receive_event(ws, expected):
    for _ in range(12):
        event = ws.receive_json()
        assert event["type"] != "error", event
        if event["type"] == expected:
            return event
    pytest.fail(f"Did not receive {expected}")


def test_guided_difficulty_defaults_to_expert_and_rejects_invalid_values(streaming_client):
    client, _ = streaming_client
    token = register(client)
    start = {"token": token, "surah": 1, "from_ayah": 1, "guided": True}
    with client.websocket_connect("/recite/live") as ws:
        ws.send_json({**start, "difficulty": "unlimited"})
        assert ws.receive_json()["type"] == "error"
    with client.websocket_connect("/recite/live") as ws:
        ws.send_json(start)
        assert receive_event(ws, "ready")["difficulty"] == "expert"
        ws.send_json({"type": "stop"})
        receive_event(ws, "finished")


def test_guided_cannot_change_difficulty_during_pause_and_resume(streaming_client, monkeypatch):
    client, fake = streaming_client

    def transcribe(audio):
        words = (["الرحمن", "الرحييم"]
                 if round(float(audio[0]) * 32768) == 6000 else ["الرحييم"])
        return [SpokenWord(word, 0.05 + i * 0.16, 0.18 + i * 0.16)
                for i, word in enumerate(words)]

    monkeypatch.setattr(fake, "transcribe_words", transcribe)
    start = {"token": register(client), "surah": 1, "from_ayah": 3,
             "guided": True, "difficulty": "intermediate"}
    with client.websocket_connect("/recite/live") as ws:
        ws.send_json(start)
        assert receive_event(ws, "ready")["difficulty"] == "intermediate"
        for _ in range(2):
            ws.send_bytes(np.full(16000, 6000, dtype="<i2").tobytes())
            receive_event(ws, "feedback")
        ws.send_json({"type": "pause"})
        paused = receive_event(ws, "paused")
        assert paused["repeat_word"] == 1
        assert paused["current_ayah"] == 3
        ws.send_json({"type": "resume", "difficulty": "expert"})
        receive_event(ws, "resumed")
        for _ in range(2):
            ws.send_bytes(np.full(16000, 8000, dtype="<i2").tobytes())
            advanced = receive_event(ws, "feedback")
        assert advanced["current_ayah"] == 4
        assert advanced["matched_words"] == 2
        ws.send_json({"type": "stop"})
        receive_event(ws, "finished")


@pytest.mark.parametrize(("difficulty", "outcome"), [("beginner", "correct"),
                                                    ("intermediate", "repeat")])
def test_guided_wire_retry_accepts_a_supported_exact_word_by_level(
    streaming_client, monkeypatch, difficulty, outcome,
):
    client, fake = streaming_client

    def transcribe(audio):
        if round(float(audio[0]) * 32768) == 6000:
            return [SpokenWord("قل", 0.05, 0.2), SpokenWord("الله", 0.25, 0.45)]
        return [SpokenWord("هو", 0.05, 0.29, reliable=False, borderline=True)]

    monkeypatch.setattr(fake, "transcribe_words", transcribe)
    with client.websocket_connect("/recite/live") as ws:
        ws.send_json({"token": register(client), "surah": 112, "from_ayah": 1,
                      "guided": True, "difficulty": difficulty})
        assert receive_event(ws, "ready")["difficulty"] == difficulty
        for _ in range(2):
            ws.send_bytes(np.full(16000, 6000, dtype="<i2").tobytes())
            flagged = receive_event(ws, "feedback")
        assert flagged["needs_retry"] and flagged["mistakes"][0]["type"] == "skipped"
        ws.send_json({"type": "pause"})
        receive_event(ws, "paused")
        ws.send_json({"type": "resume", "ayah": 1, "word_index": 1})
        assert receive_event(ws, "resumed")["retry_word"] == 1
        for amplitude in (8000, 8000, 0, 0):
            ws.send_bytes(np.full(16000, amplitude, dtype="<i2").tobytes())
            update = receive_event(ws, "feedback")
        assert update["retry_result"] == outcome
        assert update["mistakes"][0]["corrected"] is (outcome == "correct")
        assert update["current_ayah"] == 1
        assert update["scored_words"] == 2
        ws.send_json({"type": "stop"})
        receive_event(ws, "finished")


@pytest.mark.parametrize(("difficulty", "advances"), [
    ("beginner", (True, True)), ("intermediate", (False, True)), ("expert", (False, False)),
])
def test_wider_guided_policy_on_identical_websocket_audio(streaming_client, monkeypatch, difficulty, advances):
    client, fake = streaming_client

    def transcribe(audio):
        echo = round(float(audio[0]) * 32768) == 6000
        return [SpokenWord("قل", 0.02, 0.12),
                SpokenWord("هوو" if echo else "هو", 0.16, 0.30, reliable=echo, borderline=not echo),
                SpokenWord("الله", 0.33, 0.52), SpokenWord("احد", 0.55, 0.72)]

    monkeypatch.setattr(fake, "transcribe_words", transcribe)
    token = register(client)
    for amplitude, advanced in zip((6000, 8000), advances):
        with client.websocket_connect("/recite/live") as ws:
            ws.send_json({"token": token, "surah": 112, "from_ayah": 1,
                          "guided": True, "difficulty": difficulty})
            assert receive_event(ws, "ready")["difficulty"] == difficulty
            for _ in range(2):
                ws.send_bytes(np.full(16000, amplitude, dtype="<i2").tobytes())
                receive_event(ws, "feedback")
            ws.send_json({"type": "stop"})
            result = receive_event(ws, "finished")
            assert result["current_ayah"] == (2 if advanced else 1)
            assert result["matched_words"] == (4 if advanced else 1)
            if difficulty != "expert":
                assert not result["mistakes"]
            else:
                # The shipped Expert path can turn discarded ambiguity into
                # omissions when later reliable words arrive in the batch.
                assert [(m["word_index"], m["type"]) for m in result["mistakes"]] == [
                    (1, "skipped"), (2, "skipped"),
                ]


@pytest.mark.parametrize("words_into_fifth", [0, 1])
def test_guided_websocket_pause_resume_fatiha_preserves_active_ayah(
    streaming_client, monkeypatch, words_into_fifth,
):
    client, fake = streaming_client
    ref = load_reference()[1]
    fifth = ref[5]["text"].split()
    first = [word for verse in range(1, 5) for word in ref[verse]["text"].split()]
    groups = {6000: first + fifth[:words_into_fifth], 8000: fifth[words_into_fifth:]}

    def transcribe(audio):
        words = groups.get(round(float(audio[0]) * 32768), [])
        return [SpokenWord(word, 0.02 + i * 0.06, 0.075 + i * 0.06)
                for i, word in enumerate(words) if 0.075 + i * 0.06 <= len(audio) / 16000]

    monkeypatch.setattr(fake, "transcribe_words", transcribe)
    token = register(client)
    with client.websocket_connect("/recite/live") as ws:
        ws.send_json({"token": token, "surah": 1, "from_ayah": 1, "guided": True})
        assert receive_event(ws, "ready")["guided"] is True
        for _ in range(2):
            ws.send_bytes(np.full(16000, 6000, dtype="<i2").tobytes())
            receive_event(ws, "feedback")
        ws.send_json({"type": "pause"})
        paused = receive_event(ws, "paused")
        assert (paused["current_ayah"], paused["current_word"]) == (5, words_into_fifth)
        assert paused["matched_words"] == 13 + words_into_fifth
        assert paused["mistakes"] == []
        ws.send_bytes(np.full(16000, 8000, dtype="<i2").tobytes())  # Stray frame while paused.
        ws.send_json({"type": "ping"})
        ws.send_json({"type": "resume"})
        resumed = receive_event(ws, "resumed")
        assert resumed["words"] == paused["words"]
        assert (resumed["current_ayah"], resumed["current_word"]) == (5, words_into_fifth)
        for _ in range(2):
            ws.send_bytes(np.full(16000, 8000, dtype="<i2").tobytes())
            live = receive_event(ws, "feedback")
        assert live["current_ayah"] == 6
        assert live["matched_words"] == 17
        ws.send_json({"type": "stop"})
        assert receive_event(ws, "finished")["session_id"] is not None
    saved = client.get("/history", headers={"Authorization": f"Bearer {token}"}).json()["sessions"]
    assert len(saved) == 1
    assert saved[0]["correct_words"] == 17


def test_guided_websocket_isolates_retries_and_preserves_selection_on_pause(
    streaming_client, monkeypatch,
):
    client, fake = streaming_client
    transcripts = {6000: ["قُلْ", "اللَّهُ", "أَحَدٌ"], 7000: ["كتاب"],
                   8000: ["هُوَ"], 9000: ["اللَّهُ", "أَحَدٌ"]}

    def transcribe(audio):
        return [SpokenWord(word, 0.05 + i * 0.15, 0.18 + i * 0.15)
                for i, word in enumerate(transcripts.get(round(float(audio[0]) * 32768), []))]

    monkeypatch.setattr(fake, "transcribe_words", transcribe)
    token = register(client)
    with client.websocket_connect("/recite/live") as ws:
        ws.send_json({"token": token, "surah": 112, "from_ayah": 1, "guided": True})
        receive_event(ws, "ready")

        def frame(value):
            ws.send_bytes(np.full(16000, value, dtype="<i2").tobytes())
            return receive_event(ws, "feedback")

        def pause():
            ws.send_json({"type": "pause"})
            return receive_event(ws, "paused")

        def retry():
            ws.send_json({"type": "resume", "ayah": 1, "word_index": 1})
            assert receive_event(ws, "resumed")["retry_word"] == 1

        def utterance(value):
            frame(value)
            frame(value)
            frame(0)
            return frame(0)

        frame(6000)
        gate = frame(6000)
        assert gate["needs_retry"]
        assert gate["current_ayah"] == 1
        assert gate["scored_words"] == 2
        ws.send_bytes(np.full(16000, 8000, dtype="<i2").tobytes())
        assert pause()["mistakes"][0]["corrected"] is False

        retry()
        frame(7000)
        selected = pause()
        assert selected["retry_word"] == 1
        assert selected["retry_result"] is None
        ws.send_json({"type": "resume"})
        assert receive_event(ws, "resumed")["retry_word"] == 1
        failed = utterance(7000)
        assert failed["retry_result"] == "incorrect"
        assert failed["mistakes"][0]["corrected"] is False
        pause()

        retry()
        corrected = utterance(8000)
        assert corrected["retry_result"] == "correct"
        assert corrected["mistakes"][0]["corrected"] is True
        assert corrected["current_word"] == 2
        pause()
        ws.send_json({"type": "resume", "ayah": 1, "word_index": 1})
        assert "flagged word" in receive_event(ws, "control_error")["message"]
        ws.send_json({"type": "resume"})
        receive_event(ws, "resumed")
        frame(9000)
        assert frame(9000)["current_ayah"] == 2
        ws.send_json({"type": "stop"})
        assert receive_event(ws, "finished")["matched_words"] == 4
    saved = client.get("/history", headers={"Authorization": f"Bearer {token}"}).json()["sessions"]
    assert len(saved) == 1
    assert saved[0]["mistakes"][0]["corrected"] is True


def test_live_feedback_arrives_before_stop_and_history_retains_correction(streaming_client):
    client, fake = streaming_client
    token = register(client)
    frame = (np.sin(np.arange(8000) * 0.1) * 6000).astype("<i2").tobytes()
    with client.websocket_connect("/recite/live") as ws:
        ws.send_json({"token": token, "surah": 112, "from_ayah": 1})
        assert ws.receive_json()["type"] == "ready"
        ws.send_bytes(frame)
        assert ws.receive_json()["scored_words"] == 0
        ws.send_bytes(frame)
        live = ws.receive_json()
        assert live["type"] == "feedback"
        assert live["mistakes"][0]["type"] == "skipped"
        ws.send_bytes(frame)
        corrected = ws.receive_json()
        assert corrected["mistakes"][0]["corrected"] is True
        ws.send_json({"type": "stop"})
        while True:
            review = ws.receive_json()
            if review["type"] == "finished":
                break
        assert review["session_id"] is not None
        assert review["scored_words"] == 3  # No false skip of ahad or later ayahs.
    history = client.get("/history", headers={"Authorization": f"Bearer {token}"}).json()
    assert len(history["sessions"]) == 1
    mistake = history["sessions"][0]["mistakes"][0]
    assert mistake["type"] == "skipped"
    assert mistake["corrected"] is True
    assert fake.calls >= 3


def test_live_fatiha_recovers_before_stop_and_saves_only_confirmed_words(
    streaming_client, monkeypatch,
):
    client, fake = streaming_client
    hypotheses = [
        SpokenWord("بِسْمِ", 0.02, 0.18), SpokenWord("اللَّهِ", 0.2, 0.42),
        SpokenWord("رَبِّ", 0.68, 0.85),  # Disproved when ayah 2 starts.
        SpokenWord("الْحَمْدُ", 1.0, 1.18), SpokenWord("لِلَّهِ", 1.2, 1.38),
        SpokenWord("رَبِّ", 1.56, 1.72), SpokenWord("الْعَالَمِينَ", 1.8, 1.99),
        SpokenWord("الرَّحْمَانِ", 2.08, 2.24), SpokenWord("الرَّحِيمِ", 2.3, 2.49),
    ]

    def transcribe(audio):
        seconds = len(audio) / 16000
        return [SpokenWord("الرَّحْمَانَ", w.start, w.end)
                if seconds >= 3 and w is hypotheses[7] else w
                for w in hypotheses if w.end <= seconds]

    monkeypatch.setattr(fake, "transcribe_words", transcribe)
    token = register(client)
    frame = (np.sin(np.arange(8000) * 0.1) * 6000).astype("<i2").tobytes()
    with client.websocket_connect("/recite/live") as ws:
        ws.send_json({"token": token, "surah": 1, "from_ayah": 1})
        assert ws.receive_json()["type"] == "ready"
        positions = []
        for _ in range(6):
            ws.send_bytes(frame)
            update = ws.receive_json()
            assert update["type"] == "feedback"
            positions.append(update["scored_words"])
        assert positions == [0, 2, 2, 6, 8, 10]
        assert update["current_ayah"] == 4
        assert update["confirmed_words"] == 8
        assert update["mistakes"] == []
        ws.send_json({"type": "stop"})
        while (review := ws.receive_json())["type"] != "finished":
            pass
        assert review["session_id"] is not None
    history = client.get("/history", headers={"Authorization": f"Bearer {token}"}).json()
    saved = history["sessions"][0]
    assert saved["total_words"] == saved["correct_words"] == 8
    assert saved["mistakes"] == []


@pytest.mark.parametrize("kind", ["incorrect", "skipped"])
def test_live_fatiha_single_word_corrects_ayah_one_while_reading_ayah_five(
    streaming_client, monkeypatch, kind,
):
    client, fake = streaming_client
    reference = load_reference()[1]
    initial = reference[1]["text"].split()
    if kind == "incorrect":
        initial[1] = "إِلَه"
    else:
        del initial[1]
    fifth = reference[5]["text"].split()
    heard = initial + [
        word for ayah in (2, 3, 4) for word in reference[ayah]["text"].split()
    ] + fifth[:2]
    hypotheses = [SpokenWord(word, 0.02 + i * 0.14, 0.13 + i * 0.14)
                  for i, word in enumerate(heard)]
    # Repeat the one ayah-one word by itself. Then continue ayah five.
    hypotheses += [SpokenWord("اللَّهَ", 2.55, 2.78),
                   SpokenWord(fifth[2], 3.05, 3.30)]
    monkeypatch.setattr(fake, "transcribe_words", lambda audio: [
        word for word in hypotheses if word.end <= len(audio) / 16000])
    token = register(client)
    frame = (np.sin(np.arange(8000) * 0.1) * 6000).astype("<i2").tobytes()
    with client.websocket_connect("/recite/live") as ws:
        ws.send_json({"token": token, "surah": 1, "from_ayah": 1})
        assert ws.receive_json()["type"] == "ready"
        for _ in range(6):
            ws.send_bytes(frame)
            update = ws.receive_json()
        assert (update["current_ayah"], update["current_word"]) == (5, 2)
        assert [(m["ayah"], m["word_index"], m["type"], m["corrected"])
                for m in update["mistakes"]] == [(1, 1, kind, False)]
        ws.send_bytes(frame)
        corrected = ws.receive_json()
        assert (corrected["current_ayah"], corrected["current_word"]) == (5, 2)
        assert corrected["mistakes"][0]["corrected"] is True
        assert corrected["words"][1] == {
            "ayah": 1, "word_index": 1, "state": "matched", "uncertain": False}
        ws.send_bytes(frame)
        update = ws.receive_json()
        assert (update["current_ayah"], update["current_word"]) == (5, 3)
        ws.send_json({"type": "stop"})
        while (review := ws.receive_json())["type"] != "finished":
            pass
        assert review["session_id"] is not None
    saved = client.get("/history", headers={"Authorization": f"Bearer {token}"}).json()["sessions"][0]
    assert saved["correct_words"] == saved["total_words"] == 16
    assert [(m["ayah"], m["word_index"], m["type"], m["corrected"])
            for m in saved["mistakes"]] == [(1, 1, kind, True)]


def test_live_rejects_bad_auth_before_loading_model(streaming_client):
    client, fake = streaming_client
    with client.websocket_connect("/recite/live") as ws:
        ws.send_json({"token": "invalid", "surah": 112, "from_ayah": 1})
        assert ws.receive_json()["type"] == "error"
    assert fake.calls == 0


def test_silence_does_not_invoke_model_or_save_an_empty_session(streaming_client):
    client, fake = streaming_client
    token = register(client)
    with client.websocket_connect("/recite/live") as ws:
        ws.send_json({"token": token, "surah": 112, "from_ayah": 1})
        ws.receive_json()
        ws.send_bytes(bytes(16000))
        assert ws.receive_json()["mistakes"] == []
        ws.send_json({"type": "stop"})
        while (review := ws.receive_json())["type"] != "finished":
            pass
        assert review["session_id"] is None
    assert fake.calls == 0


def test_unresolved_audio_stays_unscored_in_history(streaming_client, monkeypatch):
    client, fake = streaming_client
    monkeypatch.setattr(fake, "transcribe_words", lambda _: [
        SpokenWord("قل", 0.05, 0.2, reliable=False)])
    token = register(client)
    frame = (np.sin(np.arange(8000) * 0.1) * 6000).astype("<i2").tobytes()
    with client.websocket_connect("/recite/live") as ws:
        ws.send_json({"token": token, "surah": 112, "from_ayah": 1})
        assert ws.receive_json()["type"] == "ready"
        ws.send_bytes(frame)
        ws.receive_json()
        ws.send_bytes(frame)
        update = ws.receive_json()
        assert update["words"][0]["state"] == "unconfirmed"
        assert update["matched_words"] == update["confirmed_words"] == 0
        assert update["mistakes"] == []
        ws.send_json({"type": "stop"})
        while (review := ws.receive_json())["type"] != "finished":
            pass
        assert review["session_id"] is None
    assert client.get("/history", headers={"Authorization": f"Bearer {token}"}).json()["sessions"] == []


def test_hallucinated_tail_during_pause_cannot_anchor_a_skip(streaming_client):
    client, _ = streaming_client
    token = register(client)
    voice = (np.sin(np.arange(3200) * 0.1) * 6000).astype("<i2").tobytes()
    with client.websocket_connect("/recite/live") as ws:
        ws.send_json({"token": token, "surah": 112, "from_ayah": 1})
        assert ws.receive_json()["type"] == "ready"
        ws.send_bytes(voice)
        ws.send_bytes(bytes(9600))
        assert ws.receive_json()["scored_words"] == 0
        ws.send_bytes(bytes(16000))
        pause = ws.receive_json()
        assert pause["scored_words"] == 1
        assert pause["mistakes"] == []
        ws.send_json({"type": "stop"})
        while (review := ws.receive_json())["type"] != "finished":
            pass
        assert review["scored_words"] == 1
        assert review["mistakes"] == []
