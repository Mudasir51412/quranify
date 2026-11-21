"""Ayah-scoped live recognition and explicitly selected word retries."""
from dataclasses import dataclass, replace

from .harakat import compare_word_harakat
from .live import LiveRecitation, _OPENING, _extra_repeated_letters, _joined_negation, _word_key
from .recitation_difficulty import RecitationDifficulty, RecognitionVariant, recognition_variant
from ..services.transcriber import SpokenWord


@dataclass(frozen=True)
class _Variation:
    index: int
    key: str
    anchored: bool
    segment: int
    end: float


class GuidedRecitation(LiveRecitation):
    def __init__(self, window: dict[int, str], *,
                 difficulty: RecitationDifficulty = RecitationDifficulty.EXPERT,
                 vocabulary: set[str] | None = None):
        super().__init__(window)
        self.active_ayah = self.words[0].ayah
        self.ayah_start = 0
        self.retry_index: int | None = None
        self.retry_result: str | None = None
        self.completed = False
        self.preceding_word: SpokenWord | None = None
        self.earlier_word: SpokenWord | None = None
        self.word_positions: dict[str, list[int]] = {}
        for i, word in enumerate(self.words):
            self.word_positions.setdefault(word.normalized, []).append(i)
        self.difficulty = difficulty
        self.vocabulary = (self.word_positions.keys() if vocabulary is None
                           else vocabulary.union(self.word_positions))
        self.repeat_index: int | None = None
        self._segment = 0
        self._variation: _Variation | None = None
        self._target_variation: tuple[int, str] | None = None

    @property
    def ayah_end(self) -> int:
        return self.ayah_ends[self.active_ayah]

    @property
    def blocked(self) -> bool:
        return any(not self.mistakes[i]["corrected"]
                   for i in range(self.ayah_start, self.cursor) if i in self.mistakes)

    @property
    def segment_done(self) -> bool:
        return self.completed or self.retry_result is not None or (
            self.blocked and self.retry_index is None)

    def begin_segment(self, *, ayah: int | None = None, word_index: int | None = None,
                      replay_ayah: bool = False):
        if ayah is not None and ayah != self.active_ayah:
            raise ValueError("This ayah is no longer active.")
        if word_index is not None:
            index = next((i for i in range(self.ayah_start, self.ayah_end)
                          if self.words[i].index == word_index), None)
            if not (index is not None and index in self.mistakes
                    and not self.mistakes[index]["corrected"]):
                raise ValueError("Choose a flagged word in the current ayah.")
            self.retry_index = index
        if replay_ayah and self.blocked:
            raise ValueError("Retry the flagged words first.")
        # A fresh window lets the user reread without losing verified words.
        self.retry_result = None
        self.repeat_index = None
        self._segment += 1
        self.end_segment()

    def end_segment(self):
        self.pending.clear()
        self.preceding_word = None
        self.earlier_word = None

    def _advance_ayah(self):
        if self.cursor != self.ayah_end or self.blocked:
            return
        if self.cursor == len(self.words):
            self.completed = True
            self.pending.clear()
            return
        self.active_ayah = self.words[self.cursor].ayah
        self.ayah_start = self.cursor
        self.preceding_word = None
        self.earlier_word = None

    def _retry(self, final: bool):
        # A retry is one spoken word. Wait for a breath/explicit pause so a
        # following phrase cannot accidentally satisfy the selected target.
        if not final and len(self.pending) <= 3:
            return
        if not self.pending:
            return
        index = self.retry_index
        key = _word_key("".join(w.text for w in self.pending))
        expected = self.words[index].normalized
        pausal = index + 1 == self.ayah_end and expected.endswith("ة") and key == expected[:-1] + "ه"
        heard = self.pending[0]
        variant = self._variant(expected, key) if len(self.pending) == 1 else None
        weak_exact = (len(self.pending) == 1 and key == expected and heard.borderline)
        split = (self.difficulty != RecitationDifficulty.EXPERT and key == expected
                 and self._split_evidence(self.pending))
        retry_again = self.difficulty != RecitationDifficulty.EXPERT and bool(variant or weak_exact or split)
        matched_retry = False
        if (retry_again and self.mistakes[index]["reason"] != "harakat"
                and self._retry_supported(heard, expected, variant, weak_exact, split)):
            observation = (index, key)
            matched_retry = self._beginner or self._target_variation == observation
            self._target_variation = None if matched_retry else observation
        else:
            self._target_variation = None
        if matched_retry or (len(self.pending) <= 3 and (key == expected or pausal)
                             and all(w.reliable for w in self.pending)):
            if len(self.pending) != 1 or pausal or matched_retry:
                heard = replace(heard, text=expected, reliable=True, pronunciation_evidence=False)
            errors = compare_word_harakat(
                self.words[index].text, heard.text, allow_pause=True)[0] if heard.pronunciation_evidence else []
            if not errors:
                self._match(index, heard)
        self.retry_result = ("correct" if self.mistakes[index]["corrected"]
                             else "repeat" if retry_again else "incorrect")
        self.retry_index = None
        self.pending.clear()
        self._advance_ayah()

    def _retry_supported(self, heard, expected, variant, weak_exact, split) -> bool:
        if weak_exact:
            return self._supported_borderline(heard)
        if split:
            return self._beginner or sum(not w.reliable for w in self.pending) == 1
        if not self._supported(heard) or not heard.reliable or len(expected) < 4:
            return False
        if variant in (RecognitionVariant.VOWEL, RecognitionVariant.VOWEL_ECHO, RecognitionVariant.SOUND):
            return True
        return self._beginner and variant in (RecognitionVariant.ECHO, RecognitionVariant.DOUBLE_VOWEL_ECHO)

    def accept(self, texts: list[str | SpokenWord], *, final: bool = False):
        if self.segment_done:
            return
        incoming = [SpokenWord(w, 0, 0) if isinstance(w, str) else w for w in texts]
        new_words = [w for w in incoming if _word_key(w.text)]
        self.pending.extend(new_words)
        self.transcript.extend(w.text for w in new_words)
        if self.retry_index is not None:
            self._retry(final)
            return
        while self.pending and not self.segment_done:
            heard = self.pending[0]
            key = _word_key(heard.text)
            expected = self.words[self.cursor].normalized
            if self.cursor == 0 and expected != _OPENING[0] and key == _OPENING[0]:
                prefix = tuple(_word_key(w.text) for w in self.pending[:len(_OPENING)])
                if prefix == _OPENING:
                    del self.pending[:len(_OPENING)]
                    continue
                if prefix == _OPENING[:len(prefix)]:
                    if final:
                        self.pending.clear()
                    break
            size = next((n for n in range(1, min(3, len(self.pending)) + 1)
                         if _word_key("".join(w.text for w in self.pending[:n])) == expected
                         and all(w.reliable for w in self.pending[:n])), None)
            pausal = (final or self.cursor + 1 == self.ayah_end or
                      (len(self.pending) > 1 and self.pending[1].start - heard.end >= 0.3))
            if (size is None and heard.reliable and pausal and expected.endswith("ة")
                    and key == expected[:-1] + "ه"):
                size = 1
                heard = replace(heard, pronunciation_evidence=False)
            # A decoder can join a particle already verified with its noun.
            if (size is None and heard.reliable and self.cursor > self.ayah_start
                    and self.states.get(self.cursor - 1) == "matched"
                    and key == _joined_negation(self.words[self.cursor - 1].normalized, expected)):
                size = 1
                heard = replace(heard, text=expected, pronunciation_evidence=False)
            if size is not None:
                if (size == 1 and self.difficulty != RecitationDifficulty.EXPERT
                        and self._shared_next_opening()):
                    if len(self.pending) == 1 and not final:
                        break
                    if self._next_opening_size(0) == 2:
                        self._request_repeat()
                        self.pending.clear()
                        break
                if size > 1:
                    heard = replace(heard, text=expected, pronunciation_evidence=False)
                anchor = self.pending[size - 1]
                del self.pending[:size]
                self._record_match(heard, anchor)
                continue
            borderline_expected = (self.difficulty != RecitationDifficulty.EXPERT
                                   and key == expected and heard.borderline)
            if not borderline_expected and any(w.normalized == key for w in self.words[self.ayah_start:self.cursor]):
                if heard.reliable and self.words[self.cursor - 1].normalized == key:
                    self.preceding_word = heard
                self.pending.pop(0)
                continue
            following = self.pending[1] if len(self.pending) > 1 else None
            if following and _word_key(following.text) == expected:
                self.pending.pop(0)
                continue
            if self.difficulty != RecitationDifficulty.EXPERT:
                soft = self._soft_match(heard, key, expected, final)
                if soft is not None:
                    consumed, targets = soft
                    if not consumed:
                        break
                    anchor = self.pending[consumed - 1]
                    del self.pending[:consumed]
                    for _ in range(targets):
                        self._record_match(replace(heard, text=self.words[self.cursor].text,
                                                   reliable=True, pronunciation_evidence=False), anchor)
                    continue
            at_end = self.cursor + 1 == self.ayah_end
            flagged = (self._flag_final_error(heard, key, expected, final) if at_end
                       else self._flag_local_error(heard, key, expected, following))
            if flagged:
                # The anchor verifies the position of the error. User audio
                # collected after that error belongs to the old segment.
                self.pending.clear()
                self.repeat_index = None
                self._variation = None
                return
            if (following and self.cursor + 1 < self.ayah_end
                    and _word_key(following.text) == self.words[self.cursor + 1].normalized):
                # The audio at the expected position was inconclusive.
                # Dropping it alone would relabel the same event as a miss.
                del self.pending[:2]
                self._request_repeat()
                continue
            if final or len(self.pending) > 3:
                # Unclear speech leaves the same expected word available.
                self._request_repeat()
                self.pending.pop(0)
                continue
            break

    def _record_match(self, heard: SpokenWord, anchor: SpokenWord):
        if self.states.get(self.cursor) != "matched":
            self._match(self.cursor, heard)
        self.earlier_word = self.preceding_word
        self.preceding_word = anchor
        self.repeat_index = None
        self._variation = None
        self.cursor += 1
        self._advance_ayah()

    @property
    def _beginner(self) -> bool:
        return self.difficulty == RecitationDifficulty.BEGINNER

    def _request_repeat(self):
        if self.difficulty != RecitationDifficulty.EXPERT:
            self.repeat_index = self.cursor

    def _variant(self, expected: str, key: str) -> RecognitionVariant | None:
        if self.difficulty == RecitationDifficulty.EXPERT or key in self.vocabulary:
            return None
        return recognition_variant(expected, key)

    def _soft_match(self, heard, key, expected, final) -> tuple[int, int] | None:
        # Return (raw tokens consumed, reference words verified). A zero count
        # keeps the cursor in place while awaiting speech or a fresh reading.
        variant = self._variant(expected, key)
        if key == expected and heard.borderline:
            if self._recognize_borderline_exact(heard):
                return 1, 1
            if self._supported_borderline(heard) and self._awaiting_anchor(heard, final, handoff=True):
                return 0, 0
            self._request_repeat()
            return None
        if self.cursor + 1 < len(self.words):
            next_word = self.words[self.cursor + 1].normalized
            if key == expected + next_word and key not in self.vocabulary:
                return self._consider_join(heard, final)
        if self._beginner and self._is_short_vowel_split(expected):
            right_edge = self.pending[1]
            combined = replace(heard, end=right_edge.end)
            before, after = self._neighbors(combined, size=2)
            if before and after:
                return 2, 1
            if before and self._awaiting_anchor(combined, final, size=2):
                return 0, 0
            return self._repeat_candidate(final)
        if key and len(key) < len(expected) and expected.startswith(key):
            split = self._consider_split(heard, expected, final)
            if split is not None:
                return split
        if variant is None:
            return None
        if self._recognize_variation(heard, key, variant, final):
            return 1, 1
        if (self._supported(heard) and self._allows_variation(variant)
                and self._awaiting_anchor(heard, final,
                                          handoff=self._beginner or variant == RecognitionVariant.SOUND)):
            return 0, 0
        return self._repeat_candidate(final)

    def _is_short_vowel_split(self, expected: str) -> bool:
        # The live decoder can produce e.g. ولا + م for ولم. Preserve all
        # consonants and require the second token to be an attached fragment,
        # never strip a vowel from the same valid word when spoken on its own.
        if len(expected) != 3 or len(self.pending) < 2:
            return False
        left, right = self.pending[:2]
        tail = _word_key(right.text)
        if (not left.reliable or not self._supported(left)
                or len(tail) != 1 or tail in self.vocabulary or not (right.reliable or right.borderline)
                or not self._supported(right, minimum=0.04) or right.end - right.start > 0.16
                or not -0.02 <= right.start - left.end <= 0.08):
            return False
        joined = _word_key(left.text) + tail
        return (len(joined) == len(expected) + 1 and joined not in self.vocabulary
                and recognition_variant(expected, joined, short_split=True) == RecognitionVariant.VOWEL)

    def _repeat_candidate(self, final: bool) -> tuple[int, int]:
        self._request_repeat()
        if final or len(self.pending) > 1:
            self.pending.clear()
        return 0, 0

    def _consider_join(self, heard: SpokenWord, final: bool) -> tuple[int, int]:
        crossing = self.cursor + 1 == self.ayah_end
        if not (self._supported(heard, minimum=0.14) and heard.reliable):
            return self._repeat_candidate(final)
        before, after = self._neighbors(heard, targets=2, handoff=crossing)
        if crossing:
            # Both sides of the join must be tied to real, distinct speech.
            # A complete earlier ayah cannot be reconstructed from future audio.
            enough = before and after and (self._beginner or before + after >= 3)
        else:
            enough = before + after >= (1 if self._beginner else 2)
            if enough and before + after == 1:
                enough = self._unique_span(self.cursor - before, 3)
        if enough:
            return 1, 2
        if self._awaiting_anchor(heard, final, targets=2, handoff=crossing):
            return 0, 0
        return self._repeat_candidate(final)

    def _consider_split(self, heard: SpokenWord, expected: str, final: bool) -> tuple[int, int] | None:
        if len(self.pending) == 1:
            if not final and self._supported(heard, minimum=0.04) and (heard.reliable or heard.borderline):
                return 0, 0
            return None
        pieces = self.pending[:2]
        if _word_key("".join(w.text for w in pieces)) != expected:
            return None
        if not self._split_evidence(pieces):
            return self._repeat_candidate(final)
        right_edge = pieces[-1]
        combined = replace(heard, end=right_edge.end)
        before, after = self._neighbors(combined, size=2, handoff=self._beginner)
        weak_pieces = sum(not word.reliable for word in pieces)
        enough = (before + after >= 2 and (self._beginner or weak_pieces == 1))
        if self._beginner and weak_pieces == 1 and before + after == 1:
            enough = self._unique_span(self.cursor - before, 2)
        if enough:
            return 2, 1
        if self._awaiting_anchor(combined, final, size=2, handoff=self._beginner):
            return 0, 0
        return self._repeat_candidate(final)

    def _split_evidence(self, pieces: list[SpokenWord]) -> bool:
        if (len(pieces) != 2 or all(w.reliable for w in pieces)
                or any(not self._supported(w, minimum=0.04) or not (w.reliable or w.borderline)
                       for w in pieces)
                or all(_word_key(w.text) in self.vocabulary for w in pieces)):
            return False
        left, right = pieces
        return self._adjacent(left, right) and right.start - left.end <= 0.18

    @staticmethod
    def _supported(heard: SpokenWord, *, minimum: float = 0.08) -> bool:
        return heard.stable and not heard.pronunciation_evidence and heard.end - heard.start >= minimum

    def _supported_borderline(self, heard: SpokenWord) -> bool:
        return heard.borderline and self._supported(heard)

    def _anchor(self, heard: SpokenWord | None, index: int, end: int) -> bool:
        return (heard is not None and self.ayah_start <= index < end
                and heard.reliable and heard.stable
                and _word_key(heard.text) == self.words[index].normalized)

    @staticmethod
    def _adjacent(left: SpokenWord, right: SpokenWord) -> bool:
        return left.end < right.end and -0.12 <= right.start - left.end <= 1.2

    def _anchor_extent(self, targets: int, handoff: bool) -> int:
        end = self.ayah_end
        if not handoff or end == len(self.words) or self.cursor + targets < end:
            return end
        next_end = self.ayah_ends[self.words[end].ayah]
        if targets == 1 and any(end <= i < next_end for i in self.word_positions[self.words[self.cursor].normalized]):
            return end
        return next_end

    def _neighbors(self, heard: SpokenWord, *, size: int = 1, targets: int = 1,
                   handoff: bool = False) -> tuple[int, int]:
        before, after = 0, 0
        end = self._anchor_extent(targets, handoff)
        left = self.preceding_word
        if self._anchor(left, self.cursor - 1, end) and self._adjacent(left, heard):
            before = 1
            earlier = self.earlier_word
            if self._anchor(earlier, self.cursor - 2, end) and self._adjacent(earlier, left):
                before = 2
        right = heard
        for offset, word in enumerate(self.pending[size:size + 2], start=targets):
            if not self._anchor(word, self.cursor + offset, end) or not self._adjacent(right, word):
                break
            after += 1
            right = word
        return before, after

    def _awaiting_anchor(self, heard: SpokenWord, final: bool, *, size: int = 1,
                         targets: int = 1, handoff: bool = False) -> bool:
        right = len(self.pending) - size
        if final or right >= 2 or self.cursor + targets + right >= self._anchor_extent(targets, handoff):
            return False
        _, after = self._neighbors(heard, size=size, targets=targets, handoff=handoff)
        return after == right

    def _unique_span(self, start: int, size: int) -> bool:
        keys = tuple(w.normalized for w in self.words[start:start + size])
        return not any(pos != start and keys == tuple(w.normalized for w in self.words[pos:pos + size])
                       for pos in self.word_positions[keys[0]])

    def _recognize_borderline_exact(self, heard: SpokenWord) -> bool:
        if not self._supported_borderline(heard):
            return False
        # A shared word opening the next ayah cannot establish that the old
        # ayah's last word was read.
        if (self.cursor + 1 == self.ayah_end < len(self.words)
                and self.words[self.ayah_end].normalized == self.words[self.cursor].normalized):
            return False
        before, after = self._neighbors(heard)
        if before + after >= 2:
            return True
        if self._beginner and before + after == 1 and self._unique_span(self.cursor - before, 2):
            return True
        if self.cursor + 1 != self.ayah_end:
            return False
        before, after = self._neighbors(heard, handoff=True)
        # Without a verified prefix, even two anchors are usable only for a
        # unique one-word ayah in Beginner. Future audio by itself earns no credit.
        if self._beginner and after == 2 and len(self.word_positions[self.words[self.cursor].normalized]) == 1:
            return True
        return bool(before and after and (self._beginner or after == 2))

    def _allows_variation(self, variant: RecognitionVariant) -> bool:
        if self._beginner:
            return variant != RecognitionVariant.OTHER_ECHO
        return variant in (RecognitionVariant.VOWEL, RecognitionVariant.VOWEL_ECHO, RecognitionVariant.SOUND)

    def _recognize_variation(self, heard: SpokenWord, key: str, variant: RecognitionVariant,
                             final: bool) -> bool:
        if not (self._supported(heard) and self._allows_variation(variant)):
            return False
        before, after = self._neighbors(heard, handoff=self._beginner)
        both_sides = bool(before and after)
        if not heard.reliable:
            # Beginner can use a stable near match below the strict confidence
            # gate only when exact speech surrounds it in the same ayah.
            if not (self._beginner and heard.borderline and variant in (
                RecognitionVariant.SOUND, RecognitionVariant.VOWEL, RecognitionVariant.VOWEL_ECHO
            )):
                return False
            left, right = self._neighbors(heard)
            return bool(left and right)
        if self._beginner and variant != RecognitionVariant.DOUBLE_VOWEL_ECHO and (
            before + after >= 2 or (
                before + after == 1 and self._unique_span(self.cursor - before, 2))
        ):
            return True
        if variant == RecognitionVariant.SOUND and not self._beginner:
            if len(self.words[self.cursor].normalized) < 4:
                return False
            if both_sides:
                return True
            left, right = self._neighbors(heard, handoff=True)
            if left and right and left + right >= 3:
                return True
        elif both_sides or (variant in (RecognitionVariant.VOWEL, RecognitionVariant.VOWEL_ECHO)
                            and before + after >= 2):
            return True
        previous = self._variation
        if previous is not None and (previous.index, previous.key) == (self.cursor, key):
            if previous.segment == self._segment and heard.start < previous.end + 0.05:
                return False
            if before or after or previous.anchored:
                return True
        if final or after:
            self._variation = _Variation(self.cursor, key, bool(before or after), self._segment, heard.end)
        return False

    def _next_opening_size(self, offset: int) -> int:
        if self.ayah_end == len(self.words):
            return 0
        start = self.ayah_end
        next_end = self.ayah_ends[self.words[start].ayah]
        size = min(2, next_end - start)
        spoken = self.pending[offset:offset + size]
        if len(spoken) == size and all(
            w.reliable and w.stable and _word_key(w.text) == self.words[start + i].normalized
            for i, w in enumerate(spoken)
        ):
            return size
        return 0

    def _shared_next_opening(self) -> bool:
        end = self.ayah_end
        if end + 1 >= len(self.words) or self.words[end].ayah != self.words[end + 1].ayah:
            return False
        return (self.words[self.cursor].normalized == self.words[end].normalized
                and (self.cursor + 1 == end
                     or self.words[self.cursor + 1].normalized != self.words[end + 1].normalized))

    def _flag_final_error(self, heard: SpokenWord, key: str, expected: str, final: bool) -> bool:
        if key == expected or not (heard.reliable and heard.stable):
            return False
        has_prefix = self.cursor > self.ayah_start
        if has_prefix and self._next_opening_size(0) == 2:
            if self.repeat_index == self.cursor:
                return False
            self._mistake(self.cursor, "skipped")
        else:
            if key in self.word_positions or _extra_repeated_letters(key, expected):
                return False
            prefix = self.preceding_word
            continued = (final and len(self.pending) == 1 and prefix is not None
                         and heard.end - heard.start >= 0.08
                         and -0.12 <= heard.start - prefix.end <= 1.2)
            opening = self._next_opening_size(1)
            anchored = ((opening == 2 or (opening == 1 and has_prefix))
                        and self.pending[1].start >= heard.end - 0.12)
            if not (continued or anchored):
                return False
            self._mistake(self.cursor, "incorrect")
        self.cursor += 1
        return True

    def _flag_local_error(self, heard, key, expected, following) -> bool:
        if key == expected or not (heard.reliable and heard.stable):
            return False
        limit = min(self.ayah_end, self.cursor + 4)
        target = next((i for i in range(self.cursor + 1, limit)
                       if self.words[i].normalized == key), None)
        # An omission requires context already established in this ayah or
        # two adjacent words belonging to this ayah, never the next ayah.
        paired = (target is not None and target + 1 < self.ayah_end and following
                  and following.reliable and following.stable
                  and _word_key(following.text) == self.words[target + 1].normalized)
        if target is not None and (self.cursor > self.ayah_start or paired):
            if self.repeat_index == self.cursor:
                return False
            self._advance_to(target, omission=True)
            return True
        if (not following or not (following.reliable and following.stable)
                or self.cursor + 1 >= self.ayah_end
                or _word_key(following.text) != self.words[self.cursor + 1].normalized):
            return False
        if (_extra_repeated_letters(key, expected)
                or any(i >= self.ayah_end for i in self.word_positions.get(key, []))):
            return False
        overlap = min(heard.end, following.end) - max(heard.start, following.start)
        joined = _joined_negation(expected, self.words[self.cursor + 1].normalized)
        if overlap > 0.12 or (joined and key.startswith(joined[:len(expected) + 1])):
            return False
        self._mistake(self.cursor, "incorrect")
        self.cursor += 1
        return True

    def snapshot(self) -> dict:
        review = super().snapshot()
        required = [i for i in range(self.ayah_start, self.cursor)
                    if i in self.mistakes and not self.mistakes[i]["corrected"]]
        index = self.retry_index if self.retry_index is not None else (
            required[0] if required else min(self.cursor, self.ayah_end - 1))
        review.update(
            current_ayah=self.active_ayah,
            current_word=self.words[index].index,
            completed=self.completed,
            scored_words=len(self.states),
            needs_retry=bool(required),
            retry_word=(self.words[self.retry_index].index if self.retry_index is not None else None),
            retry_result=self.retry_result,
            repeat_word=(self.words[self.repeat_index].index if self.repeat_index is not None else None),
        )
        return review
