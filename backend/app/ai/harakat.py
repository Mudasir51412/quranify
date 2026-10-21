"""
Algorithm 3 — Harakat Comparison (report §4.1.2, fixed).

Extract (base_letter, vowel, shadda) pairs from a diacritized word,
align base-letter sequences with SequenceMatcher, and compare the
vowel attached to each aligned letter.

Grouping (from report): Fathatan->Fatha, Dammatan->Damma, Kasratan->Kasra.

Fixes vs report:
- Case 50 / D03: if the heard word carries NO vowel evidence for an
  aligned letter, that is *insufficient evidence*, not proof of correct
  pronunciation. compare_harakat reports `uncertain` count separately;
  the pipeline turns a fully-unvocalized transcription into an
  UNCERTAIN result instead of PASS.
- Shadda is part of the comparison (case 35: shadda omission = error).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher

# Diacritic -> normalized vowel name
_VOWEL_MAP = {
    "\u064E": "fatha",    # ً actually fathatan below; fatha here
    "\u064B": "fatha",    # Fathatan -> Fatha
    "\u064F": "damma",    # Damma
    "\u064C": "damma",    # Dammatan -> Damma
    "\u0650": "kasra",    # Kasra
    "\u064D": "kasra",    # Kasratan -> Kasra
    "\u0652": "sukun",    # Sukun
    "\u0670": "fatha",    # superscript alef behaves like a long fatha
}
_SHADDA = "\u0651"
# Marks that are neither base letters nor vowels/shadda: ignore in pairing
_IGNORE = set("\u0640\u0610\u0611\u0612\u0613\u0614\u06D6\u06D7\u06D8\u06D9\u06DA\u06DB\u06DC\u06DD\u06DE\u06DF\u06E0\u06E1\u06E2\u06E3\u06E4\u06E5\u06E6\u06E7\u06E8\u06EA\u06EB\u06EC\u06ED")


@dataclass
class LetterPair:
    letter: str
    vowel: str | None = None  # None = no vowel evidence present
    shadda: bool = False


@dataclass
class HarakatError:
    letter: str
    expected_vowel: str | None
    heard_vowel: str | None
    expected_shadda: bool = False
    heard_shadda: bool = False
    word_index: int | None = None  # set by pipeline-level comparison


def extract_pairs(word: str) -> list[LetterPair]:
    """PROCEDURE ExtractPairs from the report."""
    pairs: list[LetterPair] = []
    if not word:
        return pairs
    for ch in word:
        if ch in _IGNORE:
            continue
        if ch in _VOWEL_MAP:
            if pairs:
                pairs[-1].vowel = _VOWEL_MAP[ch]
            continue
        if ch == _SHADDA:
            if pairs:
                pairs[-1].shadda = True
            continue
        # Any other combining mark (maddah U+0653, hamza marks, Quranic
        # annotation signs) is NOT a base letter — never create a pair.
        o = ord(ch)
        if 0x064B <= o <= 0x065F or 0x06D6 <= o <= 0x06ED:
            continue
        if "\u0600" <= ch <= "\u06FF":
            pairs.append(LetterPair(letter=ch))
    return pairs


def compare_word_harakat(reference_word: str, heard_word: str) -> tuple[list[HarakatError], int]:
    """
    Returns (errors, uncertain_count).
    uncertain_count = aligned letters where the HEARD side has no vowel
    evidence but the reference expects one.
    """
    ref_pairs = extract_pairs(reference_word)
    heard_pairs = extract_pairs(heard_word)
    if not ref_pairs or not heard_pairs:
        return [], 0
    ref_letters = [p.letter for p in ref_pairs]
    heard_letters = [p.letter for p in heard_pairs]
    matcher = SequenceMatcher(None, ref_letters, heard_letters, autojunk=False)
    errors: list[HarakatError] = []
    uncertain = 0
    for block in matcher.get_matching_blocks():
        for k in range(block.size):
            rp = ref_pairs[block.a + k]
            hp = heard_pairs[block.b + k]
            if hp.vowel is None and rp.vowel is not None:
                uncertain += 1
                continue
            if rp.vowel != hp.vowel or rp.shadda != hp.shadda:
                errors.append(HarakatError(
                    letter=rp.letter,
                    expected_vowel=rp.vowel, heard_vowel=hp.vowel,
                    expected_shadda=rp.shadda, heard_shadda=hp.shadda,
                ))
    return errors, uncertain


def compare_harakat(
    reference_words: list[str],
    heard_words: list[str],
    skipped_indices: set[int] | None = None,
) -> tuple[list[HarakatError], int]:
    """
    Word-list level comparison used by tests and the pipeline.
    Words are paired positionally after alignment by index: the caller
    (pipeline) supplies heard words already aligned 1:1 with reference
    words excluding skips. For direct use, lists are zipped in order
    and skipped indices are excluded (report case 36).
    """
    skipped = skipped_indices or set()
    all_errors: list[HarakatError] = []
    total_uncertain = 0
    for i, (rw, hw) in enumerate(zip(reference_words, heard_words)):
        if i in skipped:
            continue
        errs, unc = compare_word_harakat(rw, hw)
        for e in errs:
            e.word_index = i
        all_errors.extend(errs)
        total_uncertain += unc
    return all_errors, total_uncertain
