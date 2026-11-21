"""Bounded transcript tolerances for guided recitation."""
from enum import StrEnum

VOWEL_LETTERS = "اوي"


class RecitationDifficulty(StrEnum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    EXPERT = "expert"

class RecognitionVariant(StrEnum):
    VOWEL = "vowel"
    VOWEL_ECHO = "vowel_echo"
    SOUND = "sound"
    ECHO = "echo"
    DOUBLE_VOWEL_ECHO = "double_vowel_echo"
    EDGE_OR_SHORT_ECHO = "edge_or_short_echo"
    OTHER_ECHO = "other_echo"


# Only these substitutions are candidates. The tracker still needs timed
# contextual evidence and rejects a candidate that is another Quran word.
_SOUND_PAIRS = {frozenset(pair) for pair in ("صس", "ضظ", "طت", "ذز", "ثت", "قك", "حه")}
_SPELLING_PAIRS = {frozenset(pair) for pair in ("ىي", "ؤو", "ئي")}


def recognition_variant(expected: str, heard: str, *, short_split: bool = False) -> RecognitionVariant | None:
    """Classify a single configured sound, vowel, or repeated letter change."""
    if expected == heard or not all("ء" <= c <= "ي" for c in expected + heard):
        return None
    copies = len(heard) - len(expected)
    i = next((i for i, (a, b) in enumerate(zip(expected, heard)) if a != b),
             min(len(expected), len(heard)))
    if copies == 0 and len(expected) >= 3 and expected[i + 1:] == heard[i + 1:]:
        pair = frozenset((expected[i], heard[i]))
        if pair in _SOUND_PAIRS:
            return RecognitionVariant.SOUND
        if pair in _SPELLING_PAIRS:
            return RecognitionVariant.VOWEL
    if (len(expected) >= 2 and copies in (1, 2) and i >= 1
            and heard[i:i + copies] == expected[i - 1] * copies
            and heard[i + copies:] == expected[i:]):
        internal = len(expected) >= 5 and 2 <= i < len(expected)
        if i >= 2 and expected[i - 2] == heard[i]:
            return RecognitionVariant.OTHER_ECHO
        if copies == 2:
            if internal and heard[i] in VOWEL_LETTERS:
                return RecognitionVariant.DOUBLE_VOWEL_ECHO
            return RecognitionVariant.OTHER_ECHO
        if not internal:
            return RecognitionVariant.EDGE_OR_SHORT_ECHO
        return RecognitionVariant.VOWEL_ECHO if heard[i] in VOWEL_LETTERS else RecognitionVariant.ECHO
    # An internal long-vowel spelling can appear or disappear in the decoder.
    # Keep all consonants and the first/last letters, including any particles.
    if abs(copies) == 1 and len(expected) >= (3 if short_split else 4):
        longer, shorter = (heard, expected) if copies > 0 else (expected, heard)
        if 0 < i < len(longer) - 1 and longer[i] in VOWEL_LETTERS and longer[i + 1:] == shorter[i:]:
            return RecognitionVariant.VOWEL
    return None
