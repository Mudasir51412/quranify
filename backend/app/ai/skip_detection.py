"""
Algorithm 2 — Skipped-Word Detection (report §4.1.2).

Phase 1: exact sequence alignment via difflib.SequenceMatcher.
Phase 2: for each unmatched reference word, fuzzy-match against unused
transcribed words; character similarity >= threshold (default 0.70,
empirical from report) counts as matched, otherwise it is a skip.

Also handles split tokens: a transcribed word split into two adjacent
tokens whose combined length is 60%-140% of the reference word can
match it (report §4.1.2 Harakat preprocessing note, applied here too).
"""
from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from .normalization import fix_whisper


@dataclass
class SkippedWord:
    index: int  # ayah-local, zero-based (contract from report §4.4)
    word: str   # reference word (normalized form)


def _ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def detect_skips(reference: str, transcription: str, threshold: float = 0.70) -> list[SkippedWord]:
    ref_words = fix_whisper(reference).split() if reference else []
    heard_words = fix_whisper(transcription).split() if transcription else []
    if not ref_words:
        return []
    if not heard_words:
        return [SkippedWord(i, w) for i, w in enumerate(ref_words)]

    matcher = SequenceMatcher(None, ref_words, heard_words, autojunk=False)
    matched_ref: set[int] = set()
    used_heard: set[int] = set()
    for block in matcher.get_matching_blocks():
        for k in range(block.size):
            matched_ref.add(block.a + k)
            used_heard.add(block.b + k)

    skips: list[SkippedWord] = []
    unused_heard = [j for j in range(len(heard_words)) if j not in used_heard]

    for i, rw in enumerate(ref_words):
        if i in matched_ref:
            continue
        # Phase 2a: single-token fuzzy match
        best_j, best_score = None, 0.0
        for j in unused_heard:
            s = _ratio(rw, heard_words[j])
            if s > best_score:
                best_j, best_score = j, s
        if best_score >= threshold and best_j is not None:
            unused_heard.remove(best_j)
            matched_ref.add(i)
            continue
        # Phase 2b: split-token match (two adjacent heard tokens combined)
        matched_split = False
        ordered_unused = sorted(unused_heard)
        for idx in range(len(ordered_unused) - 1):
            j1, j2 = ordered_unused[idx], ordered_unused[idx + 1]
            if j2 != j1 + 1:
                continue
            combined = heard_words[j1] + heard_words[j2]
            if rw and 0.60 * len(rw) <= len(combined) <= 1.40 * len(rw):
                if _ratio(rw, combined) >= threshold:
                    unused_heard.remove(j1)
                    unused_heard.remove(j2)
                    matched_ref.add(i)
                    matched_split = True
                    break
        if not matched_split:
            skips.append(SkippedWord(i, rw))
    return skips
