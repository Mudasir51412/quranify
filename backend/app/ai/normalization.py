"""
Algorithm 1 — Text Normalization (from Quranify report §4.1.2, fixed).

Applied identically to reference and transcription before word alignment.
Diacritics are stripped HERE for skip detection; the original diacritized
reference is retained separately for Harakat comparison.

Fix vs report implementation:
- Case 3 (Damma) failed in their run. Root cause class: inconsistent
  diacritic removal. Here ALL marks in U+064B..U+065F (which includes
  Dammatan U+064C, Fathatan U+064B, Kasratan U+064D, Fatha U+064E,
  Damma U+064F, Kasra U+0650, Shadda U+0651, Sukun U+0652) are removed
  by a single explicit set — no per-vowel special cases to drift.
"""
from __future__ import annotations

import re

# All diacritic / annotation marks to strip for normalized comparison
_DIACRITIC_RANGES = [
    (0x064B, 0x065F),  # tanween, harakat, shadda, sukun, etc. (includes Damma U+064F)
    (0x0610, 0x061A),  # Arabic sign marks
    (0x06D6, 0x06E8),  # Quranic annotation signs
    (0x06EA, 0x06ED),  # Quranic annotation signs
]
_DIACRITICS = {chr(c) for lo, hi in _DIACRITIC_RANGES for c in range(lo, hi + 1)}
_DIACRITICS.add("\u0640")  # tatweel / kashida
# NOTE: U+0670 superscript alef is NOT stripped. Benchmark v0 (2026-10-21)
# settled this with data: the Whisper model outputs imla'i spelling where
# the superscript alef is a full alef (العالمين, أعطيناك), so U+0670 is
# mapped to alef via _LETTER_MAP below. Known trade-off: a small set of
# conventionally defective spellings (الرحمن) normalizes to الرحمان on the
# reference side; the 0.70 fuzzy threshold in skip detection (ratio ~0.93)
# absorbs that, and it caused zero false skips in benchmark v0.

# Letter variant standardization
_LETTER_MAP = {
    "\u0622": "\u0627",  # آ Alef Madd -> ا
    "\u0623": "\u0627",  # أ Alef Hamza above -> ا
    "\u0625": "\u0627",  # إ Alef Hamza below -> ا
    "\u0671": "\u0627",  # ٱ Alef Wasla -> ا
    "\u0670": "\u0627",  # (handled above as diacritic in some contexts; kept for safety)
}

_ARABIC_OR_SPACE = re.compile(r"[^\u0600-\u06FF\s]")


def fix_whisper(text) -> str:
    """Normalize Arabic text for word matching. Report name: fix_whisper()."""
    if not text or not isinstance(text, str):
        return ""
    chars = []
    for ch in text:
        if ch in _DIACRITICS:
            continue
        chars.append(_LETTER_MAP.get(ch, ch))
    cleaned = "".join(chars)
    # Keep Arabic-range characters and whitespace only
    cleaned = _ARABIC_OR_SPACE.sub(" ", cleaned)
    # Collapse repeated whitespace and trim
    return re.sub(r"\s+", " ", cleaned).strip()


# Public alias matching the report's pseudocode name
normalize_text = fix_whisper
