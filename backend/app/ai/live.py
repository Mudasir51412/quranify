"""Incremental recitation tracking, independent of audio transport and the model.

Only stable spoken words enter the tracker. Unheard tails and silence are never
scored. A later matching word establishes a skip; a replacement needs a following
anchor. Corrections may revisit earlier mistakes without rewinding progress.
"""
from dataclasses import dataclass
from difflib import SequenceMatcher
from itertools import groupby

from .harakat import compare_word_harakat
from .normalization import fix_whisper
from ..services.transcriber import SpokenWord


def _extra_repeated_letters(heard: str, expected: str) -> bool:
    """Extra identical letters can be ASR's spelling of a sustained sound.

    This only establishes ambiguity, never correct pronunciation. Requiring
    every reference run to remain intact avoids collapsing genuine doubles.
    """
    source = [(letter, len(list(run))) for letter, run in groupby(heard)]
    target = [(letter, len(list(run))) for letter, run in groupby(expected)]
    return (len(heard) > len(expected) and len(source) == len(target)
            and all(a == b and count >= required
                    for (a, count), (b, required) in zip(source, target)))


class StableWords:
    """Local agreement on two successive, overlapping timestamped hypotheses."""

    def __init__(self):
        self.previous: list[SpokenWord] = []
        self.committed: list[SpokenWord] = []
        self.end = 0.0

    def _uncommitted(self, words: list[SpokenWord]) -> list[SpokenWord]:
        result = []
        for word in words:
            if word.end <= self.end + 0.04 or not fix_whisper(word.text):
                continue
            # Retimestamping an old word must not count it twice. However,
            # the next *different* word may start slightly before the previous
            # end after a rolling-window realignment; do not discard it.
            already_heard = any(
                fix_whisper(old.text) == fix_whisper(word.text)
                and (abs(old.start - word.start) < 0.04 or (
                    word.start < old.end - 0.06 and abs(old.start - word.start) < 0.4))
                for old in self.committed[-24:])
            if not already_heard:
                result.append(word)
        return result

    def update(self, words: list[SpokenWord], *, final: bool = False) -> list[SpokenWord]:
        current = self._uncommitted(words)
        previous = self._uncommitted(self.previous)
        count = 0
        for old, new in zip(previous, current):
            # Preserve vowel differences: a changing harakah is still uncertain.
            if old.text.strip() != new.text.strip() or abs(old.start - new.start) > 0.4:
                break
            count += 1
        if final:
            count = len(current)
        committed = current[:count]
        if committed:
            self.end = committed[-1].end
            self.committed.extend(committed)
        self.previous = current[count:]
        return committed


@dataclass(frozen=True)
class ReferenceWord:
    ayah: int
    index: int
    text: str
    normalized: str


class LiveRecitation:
    def __init__(self, window: dict[int, str], *, allow_restarts: bool = False):
        self.words = [ReferenceWord(a, i, w, fix_whisper(w))
                      for a, text in sorted(window.items())
                      for i, w in enumerate(text.split())]
        self.cursor = 0
        self.pending: list[str] = []
        self.transcript: list[str] = []
        self.states: dict[int, str] = {}
        self.mistakes: dict[int, dict] = {}
        self.uncertain: set[int] = set()
        self.allow_restarts = allow_restarts

    def _mistake(self, index: int, kind: str, reason: str = "word"):
        word = self.words[index]
        self.states[index] = kind
        self.mistakes.setdefault(index, {
            "ayah": word.ayah, "word_index": word.index, "word": word.text,
            "type": kind, "reason": reason, "corrected": False})
        self.mistakes[index].update(type=kind, reason=reason, corrected=False)
        if reason != "harakat":
            self.mistakes[index].pop("harakat_errors", None)

    def _match(self, index: int, heard: str, *, lexical_uncertainty: bool = False):
        errors, uncertainty = compare_word_harakat(self.words[index].text, heard)
        if lexical_uncertainty:
            # Tokenization/spelling rescue advances the pointer, but cannot
            # assert correct pronunciation or clear a previous mistake.
            self.uncertain.add(index)
            if index not in self.mistakes:
                self.states[index] = "matched"
            return
        if errors:
            self._mistake(index, "incorrect", "harakat")
            self.mistakes[index]["harakat_errors"] = [
                {"letter": e.letter, "expected_vowel": e.expected_vowel or "",
                 "heard_vowel": e.heard_vowel or ""} for e in errors]
        else:
            original = self.mistakes.get(index)
            # No vowel evidence cannot clear a previous vowel error.
            if original and original["reason"] == "harakat" and uncertainty:
                self.uncertain.add(index)
                return
            self.states[index] = "matched"
            if original:
                original["corrected"] = True
        if uncertainty:
            self.uncertain.add(index)
        else:
            self.uncertain.discard(index)

    def accept(self, texts: list[str], *, final: bool = False):
        clean = [t for t in texts if fix_whisper(t)]
        self.transcript.extend(clean)
        self.pending.extend(clean)
        while self.pending:
            heard = self.pending[0]
            normalized = fix_whisper(heard)
            if self.cursor < len(self.words) and normalized == self.words[self.cursor].normalized:
                self._match(self.cursor, heard)
                self.cursor += 1
                self.pending.pop(0)
                continue

            # Whisper sometimes splits one Arabic word (e.g. ولم -> ولا م).
            # Exact joins are safe; approximate joins require the next word as
            # an anchor and remain explicitly uncertain in the final review.
            if self.cursor < len(self.words):
                expected = self.words[self.cursor].normalized
                rescued = False
                for size in range(1, min(3, len(self.pending)) + 1):
                    joined = "".join(self.pending[:size])
                    norm_joined = fix_whisper(joined)
                    exact = norm_joined == expected
                    anchored = (len(self.pending) > size and self.cursor + 1 < len(self.words)
                                and fix_whisper(self.pending[size]) == self.words[self.cursor + 1].normalized)
                    similar = SequenceMatcher(None, norm_joined, expected).ratio() >= 0.8
                    stretched = _extra_repeated_letters(norm_joined, expected)
                    if (size > 1 and exact) or (anchored and (similar or stretched)):
                        self._match(self.cursor, joined, lexical_uncertainty=not exact)
                        self.cursor += 1
                        del self.pending[:size]
                        rescued = True
                        break
                if rescued:
                    continue

            # Revisit an unresolved mistake, even after crossing an ayah boundary.
            corrections = [i for i, m in self.mistakes.items()
                           if not m["corrected"] and self.words[i].normalized == normalized]
            if corrections:
                self._match(max(corrections), heard)
                self.pending.pop(0)
                continue

            # Practice recordings may restart a phrase. Two consecutive exact
            # words establish the earlier position; a lone common word cannot.
            if self.allow_restarts and len(self.pending) > 1:
                restart = next((i for i in range(self.cursor - 1, -1, -1)
                                if i + 1 < len(self.words)
                                and self.words[i].normalized == normalized
                                and self.words[i + 1].normalized == fix_whisper(self.pending[1])), None)
                if restart is not None:
                    self.cursor = restart
                    continue

            # A repeated, correctly read word is not a new mistake.
            if any(w.normalized == normalized for w in self.words[max(0, self.cursor - 3):self.cursor]):
                self.pending.pop(0)
                continue

            target = next((i for i in range(self.cursor + 1, min(len(self.words), self.cursor + 41))
                           if self.words[i].normalized == normalized), None)
            if target is not None:
                # Long jumps need a second consecutive anchor, avoiding a common
                # word in a later ayah pulling the pointer across the passage.
                if target - self.cursor > 3 and not (
                    len(self.pending) > 1 and target + 1 < len(self.words)
                    and fix_whisper(self.pending[1]) == self.words[target + 1].normalized
                ):
                    break
                for i in range(self.cursor, target):
                    self._mistake(i, "skipped")
                self.cursor = target
                continue

            # Wrong word followed by the expected next word: substitution.
            if len(self.pending) > 1 and self.cursor < len(self.words) and (
                fix_whisper(self.pending[1]) == self.words[self.cursor].normalized
            ):
                # Extra speech before the expected word cannot stall tracking.
                self.pending.pop(0)
                continue
            if len(self.pending) > 1 and self.cursor + 1 < len(self.words) and (
                fix_whisper(self.pending[1]) == self.words[self.cursor + 1].normalized
            ):
                self._mistake(self.cursor, "incorrect")
                self.cursor += 1
                self.pending.pop(0)
                continue
            # Several unrecognized tokens may precede a later exact anchor.
            # Pair them conservatively with the words before that anchor so
            # a single ASR split cannot stall the rest of the surah forever.
            anchor = next(((j, i) for j in range(1, min(len(self.pending), 6))
                           for i in range(self.cursor + 1, min(len(self.words), self.cursor + 6))
                           if fix_whisper(self.pending[j]) == self.words[i].normalized), None)
            if anchor:
                j, i = anchor
                self._mistake(self.cursor, "incorrect")
                self.cursor += 1
                # Keep remaining heard tokens for the next reference position.
                self.pending.pop(0)
                continue
            if len(self.pending) > 12:
                # Off-passage speech cannot generate a cascade of false errors.
                self.pending.pop(0)
                continue
            break

    def snapshot(self) -> dict:
        next_word = self.words[min(self.cursor, len(self.words) - 1)]
        return {
            "status": ("uncertain" if self.uncertain or self.pending else "ok")
                      if self.cursor else "listening",
            "current_ayah": next_word.ayah,
            "current_word": next_word.index,
            "completed": self.cursor == len(self.words),
            "scored_words": self.cursor,
            "matched_words": sum(s == "matched" for s in self.states.values()),
            "uncertain_words": len(self.uncertain),
            "unconfirmed_words": len(self.pending),
            "transcription": " ".join(self.transcript),
            "words": [{"ayah": self.words[i].ayah, "word_index": self.words[i].index,
                       "state": state} for i, state in sorted(self.states.items())],
            "mistakes": list(self.mistakes.values()),
        }
