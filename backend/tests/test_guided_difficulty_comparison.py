"""Controlled recognizer-output probes, separate from audio or learner tests.

One named target per case. A stop means the current target would still need
attention after the first reading or a single selected retry.
"""
import json
from dataclasses import dataclass, fields

import pytest

from app.ai.guided import GuidedRecitation
from app.ai.recitation_difficulty import RecitationDifficulty
from app.services.transcriber import SpokenWord


INTERIOR = "غَيْرِ ٱلْمَغْضُوبِ عَلَيْهِمْ"
ENDING = "ٱلْحَمْدُ لِلَّهِ رَبِّ ٱلْعَٰلَمِينَ"
OPENING = "ٱهْدِنَا ٱلصِّرَٰطَ ٱلْمُسْتَقِيمَ"
SHORT = "قُلْ هُوَ أَحَدٌ"


@dataclass(frozen=True)
class Case:
    name: str
    ayah: str
    target: int
    heard: str
    support: str = "reliable"
    retry: bool = False
    isolated: bool = False


BENIGN = (
    Case("exact word with slightly weak decoder confidence", INTERIOR, 1, "المغضوب", "borderline"),
    Case("weak exact opening with an ayah-local continuation", OPENING, 0, "اهدنا", "borderline"),
    Case("weak exact ending after a verified prefix", ENDING, 3, "العالمين", "borderline"),
    Case("ordinary missing diacritics", INTERIOR, 1, "المغضوب"),
    Case("one vowel echo inside a longer word", INTERIOR, 1, "المغضووب"),
    Case("one consonant echo inside a longer word", INTERIOR, 1, "المغغضوب"),
    Case("one vowel echo on the last word of an ayah", ENDING, 3, "العالميين"),
    Case("two echoes of the same internal vowel", INTERIOR, 1, "المغضوووب"),
    Case("two vowel echoes on the last word of an ayah", ENDING, 3, "العالمييين"),
    Case("two distinct letter runs both change", INTERIOR, 1, "المغغضووب"),
    Case("echo on a short pronoun", SHORT, 1, "هوو"),
    Case("exact spelling with very weak evidence", INTERIOR, 1, "المغضوب", "weak"),
    Case("weak exact spelling seen in only one decode", INTERIOR, 1, "المغضوب", "tentative"),
    Case("weak exact ending without neighboring speech", ENDING, 3, "العالمين",
         "borderline", isolated=True),
    Case("exact weak spelling in a selected retry", INTERIOR, 1, "المغضوب", "borderline", retry=True),
    Case("small vowel echo in a selected retry", INTERIOR, 1, "المغضووب", retry=True),
    Case("longer vowel echo in a selected retry", INTERIOR, 1, "المغضوووب", retry=True),
)


def word(text: str, index: int, support: str = "reliable") -> SpokenWord:
    # The old implementation has no borderline signal. Its same Boolean
    # reliability input is used when running the frozen pre-change scorer.
    metadata = {"borderline": support in {"borderline", "tentative"}} if any(
        f.name == "borderline" for f in fields(SpokenWord)) else {}
    return SpokenWord(text, index * 0.35 + 0.04, index * 0.35 + 0.27,
                      reliable=support == "reliable", stable=support != "tentative", **metadata)


def run_case(case: Case, level: RecitationDifficulty) -> bool:
    tokens = case.ayah.split()
    if case.isolated:
        guided = GuidedRecitation({1: tokens[case.target]}, difficulty=level)
        guided.accept([word(case.heard, 0, case.support)], final=True)
        return guided.states.get(0) != "matched"
    guided = GuidedRecitation({1: case.ayah}, difficulty=level)
    if case.retry:
        guided.accept([word(text, i) for i, text in enumerate(tokens) if i != case.target])
        assert guided.mistakes[case.target]["type"] == "skipped"
        guided.begin_segment(ayah=1, word_index=case.target)
        guided.accept([word(case.heard, 0, case.support)], final=True)
    else:
        guided.accept([word(case.heard, i, case.support) if i == case.target else word(text, i)
                       for i, text in enumerate(tokens)], final=True)
    return guided.states.get(case.target) != "matched"


def comparison():
    return {level.value: [case.name for case in BENIGN if run_case(case, level)]
            for level in RecitationDifficulty}


def test_stop_counts_on_fixed_controlled_cases():
    assert {level: len(stops) for level, stops in comparison().items()} == {
        "beginner": 5, "intermediate": 11, "expert": 16,
    }


@pytest.mark.parametrize("level", list(RecitationDifficulty))
def test_clear_wrong_word_and_confirmed_omission_keep_the_gate(level):
    for observed, flag in ((["قل", "عظيم", "هو"], "incorrect"),
                           (["قل", "هو"], "skipped")):
        guided = GuidedRecitation({1: "قُلْ عَلِيمٌ هُوَ", 2: "اللَّهُ الصَّمَدُ"},
                                  difficulty=level, vocabulary={"عظيم"})
        guided.accept([word(text, i) for i, text in enumerate(observed)], final=True)
        assert guided.mistakes[1]["type"] == flag
        guided.accept([word("الله", 5), word("الصمد", 6)], final=True)
        assert guided.active_ayah == 1
        assert guided.blocked


def test_borderline_exact_shared_with_the_next_ayah_cannot_open_that_ayah():
    guided = GuidedRecitation({1: "قُلْ اللَّهُ", 2: "اللَّهُ الصَّمَدُ"},
                              difficulty=RecitationDifficulty.BEGINNER)
    guided.accept([word("قل", 0), word("الله", 1, "borderline"), word("الصمد", 2)], final=True)
    assert guided.active_ayah == 1
    assert guided.states == {0: "matched"}
    assert not guided.mistakes


def test_beginner_does_not_use_one_anchor_if_the_same_pair_occurs_in_another_ayah():
    guided = GuidedRecitation({1: "الرَّحْمَٰنِ الرَّحِيمِ", 2: "الرَّحْمَٰنِ الرَّحِيمِ"},
                              difficulty=RecitationDifficulty.BEGINNER)
    guided.accept([word("الرحمن", 0, "borderline"), word("الرحيم", 1)], final=True)
    assert guided.active_ayah == 1
    assert guided.states == {}


def test_intermediate_waits_for_the_second_following_word_across_feedback_frames():
    guided = GuidedRecitation({1: OPENING}, difficulty=RecitationDifficulty.INTERMEDIATE)
    guided.accept([word("اهدنا", 0, "borderline")])
    assert guided.snapshot()["repeat_word"] is None
    guided.accept([word("الصراط", 1)])
    assert guided.states == {}
    assert guided.snapshot()["repeat_word"] is None
    guided.accept([word("المستقيم", 2)])
    assert guided.completed


def test_beginner_cannot_accept_a_widened_candidate_that_is_a_known_word():
    guided = GuidedRecitation({1: INTERIOR}, difficulty=RecitationDifficulty.BEGINNER,
                              vocabulary={"المغضوووب"})
    guided.accept([word("غير", 0), word("المغضوووب", 1), word("عليهم", 2)], final=True)
    assert guided.states == {0: "matched"}


if __name__ == "__main__":
    print(json.dumps(comparison(), indent=2))
