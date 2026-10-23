"""The original whole-phrase checker with narrowly scoped recognition repairs.

Do not infer correctness from fuzzy spelling or erase unrelated mistakes
because one word is uncertain. Another decode must not clear observed errors.
"""
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from .harakat import compare_word_harakat, extract_pairs
from .live import _extra_repeated_letters
from .normalization import fix_whisper
from .pipeline import _aligned_heard_words, analyze_recitation
from ..services.transcriber import Recognition


@dataclass
class PracticeResult:
    states: list[str]
    mistakes: dict[int, dict] = field(default_factory=dict)

    @property
    def retry_words(self) -> list[int]:
        return [i for i, state in enumerate(self.states) if state == "retry"]

    def retry(self, indices):
        for i in indices:
            self.states[i] = "retry"
            self.mistakes.pop(i, None)


def _repair_tokens(reference: str, transcription: str) -> tuple[str, set[int]]:
    ref = [fix_whisper(w) for w in reference.split()]
    heard = [w for w in transcription.split() if fix_whisper(w)]
    # Use the last immediate repetition, preserving reference multiplicity.
    adjacent = {a for a, b in zip(ref, ref[1:]) if a == b}
    deduplicated = []
    for word in heard:
        if (deduplicated and fix_whisper(word) == fix_whisper(deduplicated[-1])
                and fix_whisper(word) not in adjacent):
            deduplicated[-1] = word
        else:
            deduplicated.append(word)
    heard = deduplicated
    retries = set()
    position = 0
    while position < len(heard):
        for size in (3, 2):
            if position + size > len(heard):
                continue
            parts = heard[position:position + size]
            if all(fix_whisper(w) in ref for w in parts):
                continue  # Recognizable passage words are not split fragments.
            joined = "".join(parts)
            normalized = fix_whisper(joined)
            before = fix_whisper(heard[position - 1]) if position else None
            after = fix_whisper(heard[position + size]) if position + size < len(heard) else None
            candidates = [i for i, word in enumerate(ref)
                          if (before == ref[i - 1] if i else before is None)
                          and (after == ref[i + 1] if i + 1 < len(ref) else after is None)
                          and (normalized == word or (
                              any(len(fix_whisper(p)) <= 2 for p in parts)
                              and SequenceMatcher(None, normalized, word).ratio() >= 0.8))]
            if len(candidates) == 1:
                i = candidates[0]
                if normalized != ref[i]:
                    retries.add(i)
                heard[position:position + size] = [joined]
                break
        position += 1
    for position, heard_word in enumerate(heard):
        normalized = fix_whisper(heard_word)
        before = fix_whisper(heard[position - 1]) if position else None
        after = fix_whisper(heard[position + 1]) if position + 1 < len(heard) else None
        candidates = [i for i, word in enumerate(ref)
                      if _extra_repeated_letters(normalized, word)
                      and (before == ref[i - 1] if i else before is None)
                      and (after == ref[i + 1] if i + 1 < len(ref) else after is None)]
        if len(candidates) == 1:
            i = candidates[0]
            # A positioning placeholder only; the explicit retry below means
            # this must never be counted as correctly recited evidence.
            heard[position] = reference.split()[i]
            retries.add(i)
    return " ".join(heard), retries


def _same_orthography(reference: str, heard: str) -> bool:
    # A known defective spelling after superscript-alef normalization; do not
    # generalize this to arbitrary similar consonants.
    return {reference, heard} <= {"الرحمان", "الرحمن"}


def assess_practice(reference: str, recognition: Recognition) -> PracticeResult:
    words = reference.split()
    result = PracticeResult(["matched"] * len(words))
    if not recognition.reliable or not fix_whisper(recognition.text):
        result.retry(range(len(words)))
        return result
    transcript, split_retries = _repair_tokens(reference, recognition.text)
    baseline = analyze_recitation(reference, transcript)
    skipped = {s.index for s in baseline.skips}
    aligned = _aligned_heard_words(reference, transcript, skipped)
    if not aligned:
        result.retry(range(len(words)))
        return result
    raw_heard = transcript.split()
    replacements = set()
    matcher = SequenceMatcher(None, [fix_whisper(w) for w in words],
                              [fix_whisper(w) for w in raw_heard], autojunk=False)
    for kind, first, last, start, end in matcher.get_opcodes():
        # A replacement between established words is wrong, not an omission.
        if kind == "replace" and last - first == end - start:
            for i, j in zip(range(first, last), range(start, end)):
                if i in skipped:
                    replacements.add(i)
                aligned[i] = raw_heard[j]
                skipped.discard(i)
    for i in skipped:
        result.states[i] = "skipped"
        result.mistakes[i] = {"type": "skipped", "reason": "word"}
    low = {fix_whisper(w) for w in recognition.low_confidence_words}
    for i, reference_word in enumerate(words):
        if i in skipped:
            continue
        heard_word = aligned.get(i)
        if heard_word is None:
            result.retry([i])
            continue
        expected, heard = fix_whisper(reference_word), fix_whisper(heard_word)
        if i in replacements:
            result.states[i] = "incorrect"
            result.mistakes[i] = {"type": "incorrect", "reason": "word"}
            continue
        if heard in low or i in split_retries or _extra_repeated_letters(heard, expected):
            result.retry([i])
            continue
        if expected != heard and not _same_orthography(expected, heard):
            # Keep the old checker's tolerance for ASR spelling, but do not
            # present a changed consonant as verified correct pronunciation.
            result.retry([i])
            continue
        errors, uncertain = compare_word_harakat(reference_word, heard_word)
        # ASR sometimes puts the same long-a mark on its alif carrier instead
        # of the preceding letter (e.g. ولاَ). This is a rendering difference,
        # not an observed change between two short vowels.
        errors = [e for e in errors if not (e.letter == "ا" and e.expected_vowel is None
                  and e.heard_vowel == "fatha" and e.expected_shadda == e.heard_shadda)]
        final_letter = extract_pairs(reference_word)[-1].letter if extract_pairs(reference_word) else None
        if (errors and i == len(words) - 1 and all(e.letter == final_letter
                and e.expected_shadda == e.heard_shadda
                and e.expected_vowel is not None and e.heard_vowel is not None for e in errors)):
            # A lone phrase-final vowel is unreliable in paused recitation.
            # Ask for another attempt; never turn this discrepancy into a pass.
            result.retry([i])
            continue
        if errors:
            result.states[i] = "incorrect"
            result.mistakes[i] = {"type": "incorrect", "reason": "harakat", "harakat_errors": [
                {"letter": e.letter, "expected_vowel": e.expected_vowel or "",
                 "heard_vowel": e.heard_vowel or "", "expected_shadda": e.expected_shadda,
                 "heard_shadda": e.heard_shadda} for e in errors]}
        elif uncertain and not any(p.vowel is not None for p in extract_pairs(heard_word)):
            # Restore the earlier handling of partially vocalized ASR text.
            # Completely absent vowel evidence still requires another attempt.
            result.retry([i])
    result.retry(split_retries)
    return result
