"""Fixed passage probes defined before the wider guided scoring policy.

These are controlled recognizer outputs against the loaded Quran reference,
not recorded learner speech. A stop means the named target is still unverified
after this first reading (or first targeted retry). Handoffs also require credit
for the next ayah's opening word in the same stream.
"""
import json
from dataclasses import dataclass, replace
from functools import lru_cache

import pytest

from app.ai.guided import GuidedRecitation
from app.ai.live import _word_key
from app.ai.recitation_difficulty import RecitationDifficulty
from app.ai.reference import load_reference
from app.services.transcriber import SpokenWord


@dataclass(frozen=True)
class Probe:
    name: str
    surah: int
    first: int
    target: int
    heard: tuple[str, ...]
    borderline: tuple[int, ...] = ()
    replaces: int = 1
    next_ayah: bool = False
    retry: bool = False
    fast: bool = False


PROBES = (
    Probe("Fatiha 2 mid-ayah exact below confidence gate", 1, 2, 1, ("لله",), (0,)),
    Probe("Fatiha 4 opening exact below confidence gate", 1, 4, 0, ("مالك",), (0,)),
    Probe("Fatiha 4 mid-ayah short final consonant echo", 1, 4, 1, ("يومم",)),
    Probe("Fatiha 4 final extra consonant into next ayah", 1, 4, 2, ("الدينن",), next_ayah=True),
    Probe("Fatiha 5 final exact below confidence gate", 1, 5, 3, ("نستعين",), (0,)),
    Probe("Fatiha 6 opening exact split with a weak piece", 1, 6, 0, ("اه", "دنا"), (0,)),
    Probe("Fatiha 6 interior s/sad", 1, 6, 1, ("السراط",)),
    Probe("Fatiha 6 final qaf/kaf into next ayah", 1, 6, 2, ("المستكيم",), next_ayah=True),
    Probe("Fatiha 7 internal short-to-long vowel", 1, 7, 2, ("انعامت",)),
    Probe("Fatiha 7 internal long vowel omitted", 1, 7, 5, ("المغضب",)),
    Probe("Fatiha 7 joined ending with lost negation vowel", 1, 7, 7, ("وللضالين",), replaces=2),
    Probe("Asr 1 one-word ayah exact below gate into next ayah", 103, 1, 0, ("والعصر",), (0,), next_ayah=True),
    Probe("Asr 2 exact join in quick audio", 103, 2, 1, ("الانسانلفى",), replaces=2, fast=True),
    Probe("Asr 2 exact split in quick audio", 103, 2, 1, ("ال", "انسان"), (1,), fast=True),
    Probe("Kawthar 1 middle emphatic/plain", 108, 1, 1, ("اعتيناك",)),
    Probe("Kawthar 1 final dot confusion", 108, 1, 2, ("الكوتر",)),
    Probe("Kawthar 2 joined start", 108, 2, 0, ("فصللربك",), replaces=2),
    Probe("Kawthar 2 final h/ha into next ayah", 108, 2, 2, ("وانهر",), next_ayah=True),
    Probe("Ikhlas 1 short pronoun echo", 112, 1, 1, ("هوو",), fast=True),
    Probe("Ikhlas 1 joined first two short words", 112, 1, 0, ("قلهو",), replaces=2, fast=True),
    Probe("Ikhlas 1 joined final and next opening", 112, 1, 3, ("احدالله",), replaces=2, next_ayah=True),
    Probe("Ikhlas 2 final s/sad at handoff", 112, 2, 1, ("السمد",), next_ayah=True),
    Probe("Ikhlas 3 short exact below gate in quick audio", 112, 3, 0, ("لم",), (0,), fast=True),
    Probe("Ikhlas 4 mid-ayah exact split with both pieces below gate", 112, 4, 3, ("كف", "وا"), (0, 1)),
    Probe("Falaq 1 mid-ayah dh/z", 113, 1, 1, ("اعوز",)),
    Probe("Falaq 1 joined second half", 113, 1, 2, ("بربالفلق",), replaces=2),
    Probe("Falaq 3 beginning exact below gate", 113, 3, 0, ("ومن",), (0,)),
    Probe("Falaq 3 short final qaf/kaf", 113, 3, 4, ("وكب",)),
    Probe("Nas 4 vowel omission in selected retry", 114, 4, 2, ("الوسوس",), retry=True),
    Probe("Nas 4 final nonlexical emphatic substitution", 114, 4, 3, ("الخناص",)),
    Probe("Ikhlas 1 borderline exact short selected retry", 112, 1, 1, ("هو",), (0,), retry=True),
    Probe("Fatiha 5 exact split selected retry", 1, 5, 1, ("نع", "بد"), (1,), retry=True),
    Probe("Falaq 1 unambiguous dh/z selected retry", 113, 1, 1, ("اعوز",), retry=True),
    Probe("Kawthar 3 clear normalized exact control", 108, 3, 1, ("شانئك",)),
)


@lru_cache(maxsize=1)
def vocabulary():
    return {_word_key(word) for surah in load_reference().values()
            for ayah in surah.values() for word in ayah["text"].split()}


def observed(texts, borderline=(), *, fast=False):
    duration = 0.15 if fast else 0.26
    return [SpokenWord(text, round(i * (duration + .05) + .02, 3),
                       round(i * (duration + .05) + .02 + duration, 3),
                       reliable=i not in borderline, borderline=i in borderline)
            for i, text in enumerate(texts)]


def passes(probe, level):
    reference = load_reference()[probe.surah]
    # Include the rest of the real surah, as the phone endpoint does.
    window = {a: row["text"] for a, row in reference.items() if a >= probe.first}
    words = window[probe.first].split()
    guided = GuidedRecitation(window, difficulty=level, vocabulary=vocabulary())
    if probe.retry:
        guided.accept(observed(words[:probe.target] + words[probe.target + 1:]), final=True)
        assert guided.mistakes[probe.target]["type"] == "skipped", probe.name
        guided.begin_segment(ayah=probe.first, word_index=probe.target)
        guided.accept(observed(probe.heard, probe.borderline), final=True)
        return guided.mistakes[probe.target]["corrected"]
    if probe.next_ayah:
        handoff = len(words)
        words.extend(window[probe.first + 1].split())
    spoken = words[:probe.target] + list(probe.heard) + words[probe.target + probe.replaces:]
    tokens = observed(spoken, {probe.target + i for i in probe.borderline}, fast=probe.fast)
    for token in tokens:  # Exercise incremental delivery before the natural pause.
        guided.accept([token])
    guided.accept([], final=True)
    return (guided.states.get(probe.target) == "matched"
            and (not probe.next_ayah or guided.states.get(handoff) == "matched"))


def comparison():
    return {level.value: [p.name for p in PROBES if not passes(p, level)]
            for level in RecitationDifficulty}


def test_wider_policy_on_frozen_recognizer_probes():
    stops = comparison()
    assert {level: len(cases) for level, cases in stops.items()} == {
        "beginner": 2, "intermediate": 15, "expert": 33,
    }
    assert set(stops["beginner"]) <= set(stops["intermediate"]) <= set(stops["expert"])
    assert stops["expert"] == [probe.name for probe in PROBES[:-1]]


@pytest.mark.parametrize("level", list(RecitationDifficulty))
@pytest.mark.parametrize(("changed", "verdict"), [("عبد", "incorrect"), (None, "skipped")])
def test_lexical_near_miss_and_confirmed_skip_still_gate(level, changed, verdict):
    surah = load_reference()[109]
    window = {a: surah[a]["text"] for a in (4, 5, 6)}
    guided = GuidedRecitation(window, difficulty=level, vocabulary=vocabulary())
    spelling = ["ولا", "انا"] + ([changed] if changed else []) + ["ما", "عبدتم"]
    # عبد is only one long vowel away from عابد, and it is a different
    # attested Quran word even though this selected passage lacks that form.
    assert "عبد" in vocabulary()
    guided.accept(observed(spelling), final=True)
    assert guided.mistakes[2]["type"] == verdict
    assert guided.blocked
    guided.accept(observed(window[5].split()), final=True)
    assert guided.active_ayah == 4
    assert all(index < 5 for index in guided.states)


@pytest.mark.parametrize("level", list(RecitationDifficulty))
def test_out_of_order_speech_and_unanchored_cross_ayah_join_earn_no_credit(level):
    surah = load_reference()[103]
    window = {a: surah[a]["text"] for a in (1, 2)}
    for speech in (window[2].split(), ["والعصران", *window[2].split()[1:]]):
        guided = GuidedRecitation(window, difficulty=level, vocabulary=vocabulary())
        guided.accept(observed(speech), final=True)
        assert guided.active_ayah == 1
        assert not guided.states


@pytest.mark.parametrize("level", list(RecitationDifficulty))
def test_silence_and_noncorroborated_speech_do_not_score(level):
    window = {1: load_reference()[112][1]["text"]}
    for changes in ({"borderline": False}, {"stable": False}, {"pronunciation_evidence": True}):
        guided = GuidedRecitation(window, difficulty=level, vocabulary=vocabulary())
        guided.accept([], final=True)
        assert not guided.states and not guided.mistakes
        tokens = observed(["قل", "هو", "الله", "احد"], (1,))
        tokens[1] = replace(tokens[1], **changes)
        guided.accept(tokens, final=True)
        assert guided.states.get(1) != "matched"
        if level != RecitationDifficulty.EXPERT:
            assert guided.states == {0: "matched"}
            assert not guided.mistakes


def test_beginner_joins_only_an_attached_consonant_in_the_captured_ikhlas_case():
    ref = load_reference()[112]
    window = {a: ref[a]["text"] for a in (3, 4)}
    # Replayed committed tokens from the real normal-speed GPU smoke. The
    # recognizer emitted the separate valid word ولا and a 60 ms م fragment.
    speech = [SpokenWord("لم", 5.60, 6.03), SpokenWord("يلد", 6.03, 6.64),
              SpokenWord("ولا", 6.64, 7.26), SpokenWord("م", 7.26, 7.32, reliable=False, borderline=True),
              SpokenWord("يولد", 7.32, 8.08), SpokenWord("ولم", 8.66, 9.34),
              SpokenWord("يكن", 9.34, 10.06)]
    for level in RecitationDifficulty:
        guided = GuidedRecitation(window, difficulty=level, vocabulary=vocabulary())
        for token in speech:
            guided.accept([token])
        guided.accept([], final=True)
        assert (guided.active_ayah == 4) is (level == RecitationDifficulty.BEGINNER)

    for fragment in ([], [replace(speech[3], stable=False)],
                     [replace(speech[3], start=7.65, end=7.72)]):
        guided = GuidedRecitation(window, difficulty=RecitationDifficulty.BEGINNER, vocabulary=vocabulary())
        guided.accept(speech[:3] + fragment + speech[4:], final=True)
        assert guided.active_ayah == 3
        assert guided.states.get(2) != "matched"
        if not fragment:
            assert guided.mistakes[2]["type"] == "incorrect"


def test_beginner_can_use_a_borderline_near_match_when_exact_speech_surrounds_it():
    window = {1: load_reference()[113][1]["text"]}
    tokens = observed(["قل", "اعوز", "برب", "الفلق"], (1,))
    for level in RecitationDifficulty:
        guided = GuidedRecitation(window, difficulty=level, vocabulary=vocabulary())
        guided.accept(tokens, final=True)
        assert guided.completed is (level == RecitationDifficulty.BEGINNER)
    guided = GuidedRecitation(window, difficulty=RecitationDifficulty.BEGINNER, vocabulary=vocabulary())
    guided.accept(tokens[1:], final=True)
    assert guided.states.get(1) != "matched"


def test_lower_modes_can_credit_a_borderline_word_repeated_at_a_distinct_position():
    window = {7: load_reference()[1][7]["text"]}
    words = window[7].split()
    for level in (RecitationDifficulty.BEGINNER, RecitationDifficulty.INTERMEDIATE):
        guided = GuidedRecitation(window, difficulty=level, vocabulary=vocabulary())
        guided.accept(observed(words, (6,)), final=True)
        assert guided.completed


@pytest.mark.parametrize("level", [RecitationDifficulty.BEGINNER, RecitationDifficulty.INTERMEDIATE])
def test_confirmed_skip_still_blocks_on_a_fresh_read_after_ambiguous_speech(level):
    window = {1: load_reference()[112][1]["text"]}
    guided = GuidedRecitation(window, difficulty=level, vocabulary=vocabulary())
    tokens = observed(["قل", "هو", "الله", "احد"], (1,))
    tokens[1] = replace(tokens[1], stable=False)
    guided.accept(tokens, final=True)
    assert guided.snapshot()["repeat_word"] == 1 and not guided.mistakes
    guided.begin_segment(ayah=1, replay_ayah=True)
    guided.accept(observed(["الله", "احد"]), final=True)
    assert guided.mistakes[1]["type"] == "skipped"
    assert guided.blocked


def test_intermediate_requires_independent_supported_near_retries():
    window = {1: load_reference()[113][1]["text"]}
    guided = GuidedRecitation(window, difficulty=RecitationDifficulty.INTERMEDIATE, vocabulary=vocabulary())
    guided.accept(observed(["قل", "برب", "الفلق"]), final=True)
    for text, outcome in (("اعوز", "repeat"), ("كتاب", "incorrect"),
                          ("اعوز", "repeat"), ("اعوز", "correct")):
        guided.begin_segment(ayah=1, word_index=1)
        guided.accept(observed([text]), final=True)
        assert guided.retry_result == outcome
    assert guided.mistakes[1]["corrected"]


if __name__ == "__main__":
    print(json.dumps(comparison(), indent=2))
