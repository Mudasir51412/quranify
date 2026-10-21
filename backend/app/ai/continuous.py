"""
Huffaz continuous-mode analysis (report §4.1.2 design, implemented).

The design's core rules, honoured here:
- A rolling window covers the current Ayah and the next few Ayahs.
- A CONFIRMED-POSITION pointer scores only words up to the furthest
  in-order match. Words after the pointer are not scored (the user may
  simply not have reached them), which prevents double-counting and
  false "skipped" flags at the tail.
- Words at/before the pointer that never matched are skipped words.
- An Ayah whose words are all skipped, with a later Ayah matched, is a
  skipped Ayah.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher

from .harakat import HarakatError, compare_word_harakat
from .normalization import fix_whisper


@dataclass
class ContinuousSkip:
    ayah: int
    word_index: int  # ayah-local, zero-based
    word: str        # reference word (diacritized)


@dataclass
class ContinuousResult:
    status: str  # ok | no_match
    confirmed_ayah: int | None = None
    confirmed_word_index: int | None = None
    scored_words: int = 0      # words up to and including the pointer
    matched_words: int = 0
    skips: list[ContinuousSkip] = field(default_factory=list)
    skipped_ayahs: list[int] = field(default_factory=list)
    harakat_errors: list[HarakatError] = field(default_factory=list)
    per_ayah: dict[int, dict] = field(default_factory=dict)


def analyze_continuous(
    window: dict[int, str], transcription: str, fuzzy_threshold: float = 0.70
) -> ContinuousResult:
    ayahs = sorted(window)
    # Combined reference: (ayah, local_idx, raw_word, norm_word)
    combined: list[tuple[int, int, str, str]] = []
    for a in ayahs:
        for i, w in enumerate(window[a].split()):
            combined.append((a, i, w, fix_whisper(w)))
    heard_raw = transcription.split() if transcription else []
    heard_norm = [fix_whisper(w) for w in heard_raw]
    ref_norm = [c[3] for c in combined]

    result = ContinuousResult(status="no_match")
    if not combined or not heard_norm:
        return result

    matcher = SequenceMatcher(None, ref_norm, heard_norm, autojunk=False)
    matched: dict[int, int] = {}  # global ref idx -> heard idx
    used_heard: set[int] = set()
    for block in matcher.get_matching_blocks():
        for k in range(block.size):
            matched[block.a + k] = block.b + k
            used_heard.add(block.b + k)
    if not matched:
        return result

    furthest = max(matched)
    # Fuzzy rescue for unmatched words at/before the pointer
    for gi in range(furthest + 1):
        if gi in matched:
            continue
        best_j, best = None, 0.0
        for j in range(len(heard_norm)):
            if j in used_heard:
                continue
            s = SequenceMatcher(None, ref_norm[gi], heard_norm[j]).ratio() \
                if ref_norm[gi] and heard_norm[j] else 0.0
            if s > best:
                best_j, best = j, s
        if best_j is not None and best >= fuzzy_threshold:
            matched[gi] = best_j
            used_heard.add(best_j)

    result.status = "ok"
    result.scored_words = furthest + 1
    result.matched_words = len([g for g in matched if g <= furthest])
    c_ayah, c_idx, _, _ = combined[furthest]
    result.confirmed_ayah, result.confirmed_word_index = c_ayah, c_idx

    for gi in range(furthest + 1):
        ayah, local_idx, raw, _n = combined[gi]
        result.per_ayah.setdefault(ayah, {"total_scored": 0, "matched": 0, "skipped": 0})
        result.per_ayah[ayah]["total_scored"] += 1
        if gi in matched:
            result.per_ayah[ayah]["matched"] += 1
        else:
            result.per_ayah[ayah]["skipped"] += 1
            result.skips.append(ContinuousSkip(ayah=ayah, word_index=local_idx, word=raw))

    # Harakat comparison for matched pairs, with ayah attached
    detailed_errors = []
    for gi in range(furthest + 1):
        if gi not in matched:
            continue
        ayah, local_idx, raw, _n = combined[gi]
        errs, _ = compare_word_harakat(raw, heard_raw[matched[gi]])
        for e in errs:
            detailed_errors.append({
                "ayah": ayah, "word_index": local_idx, "letter": e.letter,
                "expected_vowel": e.expected_vowel, "heard_vowel": e.heard_vowel,
                "word": raw,
            })
    result.harakat_errors = detailed_errors  # type: ignore[assignment]

    matched_ayahs = {combined[g][0] for g in matched if g <= furthest}
    for a in ayahs:
        info = result.per_ayah.get(a)
        if info and info["matched"] == 0 and info["skipped"] > 0 \
                and any(m > a for m in matched_ayahs):
            result.skipped_ayahs.append(a)
    return result
