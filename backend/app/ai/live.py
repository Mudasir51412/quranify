"""Incremental recitation tracking, independent of audio transport and the model.

The tracker uses recognized written words. A local anchor can support an
omission, while resynchronizing across gaps leaves those positions unconfirmed.
Corrections can revisit earlier mistakes without rewinding progress.
"""
from dataclasses import dataclass, replace
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


def _word_key(text: str) -> str:
    normalized = fix_whisper(text)
    # Standard Arabic frequently omits the written dagger alif in this word.
    return "الرحمان" if normalized == "الرحمن" else normalized


_OPENING = ("بسم", "الله", "الرحمان", "الرحيم")


def _joined_negation(expected: str, following: str) -> str | None:
    # ASR can join "ولا الضالين" and render its connected sound as
    # "وللضالين". This identifies the following noun but leaves the
    # preceding particle ambiguous.
    if expected == "ولا" and following.startswith("ال"):
        return expected[:-1] + following[1:]
    return None


class StableWords:
    """Local agreement on two successive, overlapping timestamped hypotheses."""

    def __init__(self):
        self.previous: list[SpokenWord] = []
        self.committed: list[SpokenWord] = []
        self.end = 0.0

    def _uncommitted(self, words: list[SpokenWord]) -> list[SpokenWord]:
        result = []
        for word in words:
            if word.end <= self.end + 0.04 or not _word_key(word.text):
                continue
            # Retimestamping an old word must not count it twice. However,
            # the next *different* word may start slightly before the previous
            # end after a rolling-window realignment; do not discard it.
            already_heard = any(
                _word_key(old.text) == _word_key(word.text)
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
            if _word_key(old.text) != _word_key(new.text) or abs(old.start - new.start) > 0.4:
                break
            different_marks = old.text.strip() != new.text.strip()
            borderline = bool(new.borderline and (old.reliable or old.borderline))
            if different_marks or borderline != new.borderline:
                # The spelling agrees. Token confidence can vary with the
                # decoder's choice of diacritics for that same written word.
                current[count] = replace(
                    new,
                    reliable=bool(old.reliable or new.reliable) if different_marks else new.reliable,
                    pronunciation_evidence=new.pronunciation_evidence and not different_marks,
                    borderline=borderline,
                )
            count += 1
        if final:
            current[count:] = [replace(w, stable=False) for w in current[count:]]
            count = len(current)
        return self._commit(current, count)

    def flush(self) -> list[SpokenWord]:
        current = [replace(w, stable=False) for w in self._uncommitted(self.previous)]
        return self._commit(current, len(current))

    def _commit(self, current: list[SpokenWord], count: int) -> list[SpokenWord]:
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
    def __init__(self, window: dict[int, str]):
        self.words = [ReferenceWord(a, i, w, _word_key(w))
                      for a, text in sorted(window.items())
                      for i, w in enumerate(text.split())]
        self.cursor = 0
        self.pending: list[SpokenWord] = []
        self.transcript: list[str] = []
        self.states: dict[int, str] = {}
        self.mistakes: dict[int, dict] = {}
        self.uncertain: set[int] = set()
        self.ayah_starts: dict[str, list[int]] = {}
        self.ayah_ends: dict[int, int] = {}
        for i, word in enumerate(self.words):
            self.ayah_ends[word.ayah] = i + 1
            if word.index == 0:
                self.ayah_starts.setdefault(word.normalized, []).append(i)
        self.replay: tuple[int, int] | None = None

    def _mistake(self, index: int, kind: str, reason: str = "word"):
        word = self.words[index]
        self.states[index] = kind
        self.mistakes.setdefault(index, {
            "ayah": word.ayah, "word_index": word.index, "word": word.text,
            "type": kind, "reason": reason, "corrected": False})
        self.mistakes[index].update(type=kind, reason=reason, corrected=False)
        if reason != "harakat":
            self.mistakes[index].pop("harakat_errors", None)
            self.mistakes[index].pop("pronunciation_evidence", None)

    def _match(self, index: int, heard: SpokenWord, *, lexical_uncertainty: bool = False):
        if lexical_uncertainty or not heard.reliable:
            if self.states.get(index) in (None, "unconfirmed"):
                self.states[index] = "unconfirmed"
                self.uncertain.add(index)
            return
        errors, uncovered = (compare_word_harakat(
            self.words[index].text, heard.text, allow_pause=True)
            if heard.pronunciation_evidence else ([], 0))
        if errors:
            self._mistake(index, "incorrect", "harakat")
            self.mistakes[index]["pronunciation_evidence"] = True
            self.mistakes[index]["harakat_errors"] = [
                {"letter": e.letter, "expected_vowel": e.expected_vowel or "",
                 "heard_vowel": e.heard_vowel or ""} for e in errors]
        else:
            original = self.mistakes.get(index)
            # No vowel evidence cannot clear a previous vowel error.
            if original and original["reason"] == "harakat" and (
                uncovered or not heard.pronunciation_evidence
            ):
                self.uncertain.add(index)
                return
            self.states[index] = "matched"
            if original:
                original["corrected"] = True
        self.uncertain.discard(index)

    def _advance_replay(self, heard: SpokenWord, normalized: str) -> bool:
        if self.replay is None:
            return False
        start, end = self.replay
        self.replay = None
        forward = self.words[self.cursor:self.cursor + 1]
        for i in range(start, end):
            if i > start and forward and forward[0].normalized == normalized:
                break
            if self.words[i].normalized == normalized:
                if i in self.uncertain or (i in self.mistakes and not self.mistakes[i]["corrected"]):
                    self._match(i, heard)
                if i + 1 < end:
                    self.replay = (i + 1, end)
                self.pending.pop(0)
                return True
        return False

    def _substitution(self, heard: SpokenWord, anchor: SpokenWord):
        expected = self.words[self.cursor].normalized
        actual = _word_key(heard.text)
        joined = _joined_negation(expected, self.words[self.cursor + 1].normalized)
        fragment = joined and actual.startswith(joined[:len(expected) + 1])
        overlap = min(heard.end, anchor.end) - max(heard.start, anchor.start)
        if (heard.reliable and heard.stable and anchor.reliable and anchor.stable
                and not fragment and overlap <= 0.12):
            self._mistake(self.cursor, "incorrect")
        else:
            self.uncertain.add(self.cursor)
            self.states[self.cursor] = "unconfirmed"
        self.cursor += 1
        self.pending.pop(0)

    def _forward_pair(self, start: int, stop: int) -> tuple[int, int] | None:
        """Find a unique reference pair in the buffered speech and forward window."""
        end = min(len(self.words) - 1, self.cursor + 41)
        for j in range(start, min(stop, len(self.pending) - 1)):
            first, second = self.pending[j:j + 2]
            if not (first.reliable and second.reliable):
                continue
            key = (_word_key(first.text), _word_key(second.text))
            targets = [i for i in range(self.cursor, end)
                       if key == (self.words[i].normalized, self.words[i + 1].normalized)]
            if len(targets) == 1:
                return j, targets[0]
        return None

    def _advance_to(self, target: int, *, omission: bool = False):
        for i in range(self.cursor, target):
            if omission:
                self._mistake(i, "skipped")
            else:
                self.uncertain.add(i)
                self.states[i] = "unconfirmed"
        self.cursor = target

    def accept(self, texts: list[str | SpokenWord], *, final: bool = False):
        incoming = [SpokenWord(w, 0, 0) if isinstance(w, str) else w for w in texts]
        clean = [w for w in incoming if _word_key(w.text)]
        self.transcript.extend(w.text for w in clean)
        self.pending.extend(clean)
        while self.pending:
            heard = self.pending[0]
            normalized = _word_key(heard.text)
            if self.cursor == 0 and normalized == _OPENING[0] and (
                self.words[0].normalized != _OPENING[0]
            ):
                prefix = tuple(_word_key(w.text) for w in self.pending[:len(_OPENING)])
                if prefix == _OPENING:
                    del self.pending[:len(_OPENING)]
                    continue
                if not final and prefix == _OPENING[:len(prefix)]:
                    break
            next_heard = _word_key(self.pending[1].text) if len(self.pending) > 1 else None
            forward_pair = (self.cursor + 1 < len(self.words)
                            and self.words[self.cursor].normalized == normalized
                            and self.words[self.cursor + 1].normalized == next_heard)
            if forward_pair and self.replay is not None:
                start, end = self.replay
                replay_pair = tuple(w.normalized for w in self.words[start:min(start + 2, end)])
                if replay_pair != (normalized, next_heard):
                    self.replay = None
            if self._advance_replay(heard, normalized):
                continue
            starts = [i for i in self.ayah_starts.get(normalized, [])
                      if i + 1 < min(self.cursor, self.ayah_ends[self.words[i].ayah])]
            if starts and heard.reliable and not forward_pair:
                if next_heard is None and not final:
                    break
                restart = next((i for i in reversed(starts)
                                if self.words[i + 1].normalized == next_heard), None)
                if restart is not None and self.pending[1].reliable:
                    self.replay = (restart, min(self.cursor, self.ayah_ends[self.words[restart].ayah]))
                    continue
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
                if heard.reliable and self.cursor > 0:
                    previous = self.words[self.cursor - 1]
                    if (previous.ayah == self.words[self.cursor].ayah
                            and normalized == _joined_negation(previous.normalized, expected)):
                        self._match(self.cursor, replace(heard, text=expected,
                                                         pronunciation_evidence=False))
                        self.cursor += 1
                        self.pending.pop(0)
                        continue
                if heard.reliable and self.cursor + 1 < len(self.words):
                    following = self.words[self.cursor + 1]
                    if normalized == _joined_negation(expected, following.normalized):
                        self._advance_to(self.cursor + 1)
                        self._match(self.cursor, replace(heard, text=following.normalized,
                                                         pronunciation_evidence=False))
                        self.cursor += 1
                        self.pending.pop(0)
                        continue
                ayah_end = self.ayah_ends[self.words[self.cursor].ayah]
                pausal = (self.cursor + 1 == ayah_end or final or (
                    len(self.pending) > 1 and self.pending[1].start - heard.end >= 0.3))
                if pausal and expected.endswith("ة") and normalized == expected[:-1] + "ه":
                    self._match(self.cursor, replace(heard, pronunciation_evidence=False))
                    self.cursor += 1
                    self.pending.pop(0)
                    continue
                rescued = False
                for size in range(1, min(3, len(self.pending)) + 1):
                    joined = "".join(w.text for w in self.pending[:size])
                    norm_joined = _word_key(joined)
                    exact = norm_joined == expected
                    anchored = (len(self.pending) > size and self.cursor + 1 < len(self.words)
                                and self.pending[size].reliable
                                and _word_key(self.pending[size].text) == self.words[self.cursor + 1].normalized)
                    # Similar spellings of a single, separately heard word
                    # belong to substitution, even when only one letter varies.
                    approximate_split = (size > 1
                                         and any(len(_word_key(w.text)) <= 2 for w in self.pending[:size])
                                         and SequenceMatcher(None, norm_joined, expected).ratio() >= 0.8)
                    stretched = _extra_repeated_letters(norm_joined, expected)
                    if (size > 1 and exact) or (anchored and (approximate_split or stretched)):
                        self._match(self.cursor, SpokenWord(
                            joined, heard.start, self.pending[size - 1].end,
                            reliable=all(w.reliable for w in self.pending[:size])),
                            lexical_uncertainty=not exact)
                        self.cursor += 1
                        del self.pending[:size]
                        rescued = True
                        break
                if rescued:
                    continue

            # A forward pair distinguishes continued recitation from an isolated
            # repetition of a word that also appears in an earlier ayah.
            paired = self._forward_pair(0, 1)
            # Revisit an unresolved mistake, even after crossing an ayah boundary.
            corrections = [i for i in self.mistakes.keys() | self.uncertain
                           if not self.mistakes.get(i, {}).get("corrected")
                           and self.words[i].normalized == normalized]
            if corrections and not paired:
                self._match(max(corrections), heard)
                self.pending.pop(0)
                continue

            # A repeated, correctly read word is not a new mistake.
            if not paired and any(w.normalized == normalized
                                  for w in self.words[max(0, self.cursor - 3):self.cursor]):
                self.pending.pop(0)
                continue

            target = paired[1] if paired else next((
                i for i in range(self.cursor + 1, min(len(self.words), self.cursor + 41))
                if self.words[i].normalized == normalized), None)
            if target is not None and heard.reliable:
                local = (heard.stable and target - self.cursor <= 3
                         and self.words[target].ayah == self.words[self.cursor].ayah
                         and (self.cursor > 0 or paired is not None))
                if local or paired:
                    self._advance_to(target, omission=local)
                    continue

            # Wrong word followed by the expected next word: substitution.
            if len(self.pending) > 1 and self.cursor < len(self.words) and (
                next_heard == self.words[self.cursor].normalized
            ):
                # Extra speech before the expected word cannot stall tracking.
                self.pending.pop(0)
                continue
            if len(self.pending) > 1 and self.cursor + 1 < len(self.words) and (
                next_heard == self.words[self.cursor + 1].normalized
            ):
                # A recognized word from elsewhere in the passage can be a
                # fragment of a restart rather than a lexical substitution.
                self._substitution(heard if target is None else replace(heard, reliable=False),
                                   self.pending[1])
                continue
            # A restart or a noisy phrase can fill the queue before the next
            # usable pair. Check all buffered starts before pruning.
            recovery = self._forward_pair(1, len(self.pending))
            if recovery is not None:
                offset, target = recovery
                del self.pending[:offset]
                self._advance_to(target)
                continue
            # Several unrecognized tokens may precede a later exact anchor.
            # Pair them conservatively with the words before that anchor so
            # a single ASR split cannot stall the rest of the surah forever.
            anchor = any(self.pending[j].reliable
                         and _word_key(self.pending[j].text) == self.words[i].normalized
                         for j in range(1, min(len(self.pending), 6))
                         for i in range(self.cursor + 1, min(len(self.words), self.cursor + 6)))
            if anchor:
                self.uncertain.add(self.cursor)
                self.states[self.cursor] = "unconfirmed"
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
        completed = self.cursor == len(self.words)
        pending = 0 if completed else len(self.pending)
        return {
            "status": ("uncertain" if self.uncertain or pending else "ok")
                      if self.cursor else "listening",
            "current_ayah": next_word.ayah,
            "current_word": next_word.index,
            "completed": completed,
            "scored_words": self.cursor,
            "confirmed_words": sum(s != "unconfirmed" for s in self.states.values()),
            "matched_words": sum(s == "matched" for s in self.states.values()),
            "uncertain_words": len(self.uncertain),
            "unconfirmed_words": pending,
            "transcription": " ".join(self.transcript),
            "words": [{"ayah": self.words[i].ayah, "word_index": self.words[i].index,
                       "state": state, "uncertain": i in self.uncertain}
                      for i, state in sorted(self.states.items())],
            "mistakes": list(self.mistakes.values()),
        }
