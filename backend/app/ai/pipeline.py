"""
Combined recitation pipeline — the logic behind POST /analyze.

Business rules (report §5.3 decision table, implemented):
  R1 invalid audio        -> reject before scoring (enforced at API layer
                             via audio_guardrails; text pipeline mirrors it
                             for empty transcription)
  R2 invalid reference    -> reject before scoring  [FIXES case 49 / D02:
                             empty reference is an explicit rejection,
                             never a scored mismatch]
  R3 word skipped         -> report skip; exclude that word from Harakat
  R4 vowel mismatch       -> report expected vs heard vowel
  R5 all aligned + match  -> no detected mistake
  R6 insufficient vowel   -> UNCERTAIN, request retry  [FIXES case 50 / D03:
  evidence                   unvocalized transcription is NOT a pass]
"""
from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher

from .harakat import HarakatError, compare_word_harakat
from .normalization import fix_whisper
from .skip_detection import SkippedWord, detect_skips


@dataclass
class AnalysisResult:
    status: str  # "ok" | "rejected" | "uncertain"
    reason: str | None = None
    transcription: str = ""
    skips: list[SkippedWord] = field(default_factory=list)
    harakat_errors: list[HarakatError] = field(default_factory=list)
    uncertain_letters: int = 0
    total_words: int = 0

    @property
    def has_mistakes(self) -> bool:
        return bool(self.skips or self.harakat_errors)


def _aligned_heard_words(reference: str, transcription: str, skipped_idx: set[int]) -> dict[int, str]:
    """
    Align the DIACRITIZED transcription to reference words so Harakat
    can be compared word-by-word. Uses normalized alignment, returns
    {ref_index: heard_word_diacritized}.
    """
    ref_norm = fix_whisper(reference).split()
    heard_raw = transcription.split()
    heard_norm = [fix_whisper(w) for w in heard_raw]
    matcher = SequenceMatcher(None, ref_norm, heard_norm, autojunk=False)
    aligned: dict[int, str] = {}
    matched_ref: set[int] = set()
    used_heard: set[int] = set()
    for block in matcher.get_matching_blocks():
        for k in range(block.size):
            aligned[block.a + k] = heard_raw[block.b + k]
            matched_ref.add(block.a + k)
            used_heard.add(block.b + k)
    # Fuzzy pass for near-matches (same spirit as skip detection)
    from difflib import SequenceMatcher as SM
    for i, rw in enumerate(ref_norm):
        if i in matched_ref or i in skipped_idx:
            continue
        best_j, best = None, 0.0
        for j in range(len(heard_norm)):
            if j in used_heard:
                continue
            s = SM(None, rw, heard_norm[j]).ratio() if rw and heard_norm[j] else 0.0
            if s > best:
                best_j, best = j, s
        if best_j is not None and best >= 0.70:
            aligned[i] = heard_raw[best_j]
            used_heard.add(best_j)
            matched_ref.add(i)
    return aligned


def analyze_recitation(reference: str, transcription: str) -> AnalysisResult:
    # R2: invalid reference — reject before scoring
    if not reference or not isinstance(reference, str) or not fix_whisper(reference):
        return AnalysisResult(status="rejected", reason="EMPTY_REFERENCE")
    # R1 (text mirror): empty transcription = no usable input
    if not transcription or not isinstance(transcription, str) or not fix_whisper(transcription):
        ref_words = reference.split()
        return AnalysisResult(
            status="rejected", reason="EMPTY_TRANSCRIPTION",
            total_words=len(ref_words),
            skips=[SkippedWord(i, fix_whisper(w)) for i, w in enumerate(ref_words)],
        )

    ref_words_raw = reference.split()
    skips = detect_skips(reference, transcription)
    skipped_idx = {s.index for s in skips}

    aligned = _aligned_heard_words(reference, transcription, skipped_idx)
    errors: list[HarakatError] = []
    uncertain = 0
    aligned_count = 0
    for i, rw in enumerate(ref_words_raw):
        if i in skipped_idx or i not in aligned:
            continue
        aligned_count += 1
        errs, unc = compare_word_harakat(rw, aligned[i])
        for e in errs:
            e.word_index = i
        errors.extend(errs)
        uncertain += unc

    # R6: if we aligned words but got zero vowel evidence at all on the
    # heard side while errors are also zero, we cannot confirm correctness.
    total_ref_vowels = 0
    from .harakat import extract_pairs
    for i, rw in enumerate(ref_words_raw):
        if i in skipped_idx or i not in aligned:
            continue
        total_ref_vowels += sum(1 for p in extract_pairs(rw) if p.vowel is not None)
    heard_has_any_vowel = False
    for hw in aligned.values():
        if any(p.vowel is not None for p in extract_pairs(hw)):
            heard_has_any_vowel = True
            break

    if aligned_count > 0 and total_ref_vowels > 0 and not heard_has_any_vowel and not errors:
        return AnalysisResult(
            status="uncertain", reason="INSUFFICIENT_VOWEL_EVIDENCE",
            transcription=transcription, skips=skips,
            harakat_errors=[], uncertain_letters=uncertain,
            total_words=len(ref_words_raw),
        )

    return AnalysisResult(
        status="ok", transcription=transcription, skips=skips,
        harakat_errors=errors, uncertain_letters=uncertain,
        total_words=len(ref_words_raw),
    )
