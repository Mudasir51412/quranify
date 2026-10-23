"""Cached public Alafasy audio timings. No guessed word-duration fractions."""
from functools import lru_cache
from urllib.parse import urljoin, urlparse

import httpx


@lru_cache(maxsize=512)
def verse_audio(surah: int, ayah: int, word_count: int) -> tuple[str, tuple[tuple[int, int], ...]]:
    response = httpx.get(
        f"https://api.quran.com/api/v4/recitations/7/by_ayah/{surah}:{ayah}",
        params={"fields": "segments,duration"}, timeout=10)
    response.raise_for_status()
    audio = response.json()["audio_files"][0]
    if audio.get("verse_key") != f"{surah}:{ayah}":
        raise ValueError("Reference audio verse does not match")
    url = urljoin("https://verses.quran.com/", audio["url"])
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {
        "verses.quran.com", "verses.quran.foundation", "audio.qurancdn.com"
    }:
        raise ValueError("Unsupported reference audio host")
    timings = {}
    for segment in audio.get("segments", []):
        # This endpoint supplies [start_word, end_word_exclusive, start_ms, end_ms].
        if len(segment) != 4:
            raise ValueError("Unsupported word timing format")
        first, last, start, end = segment
        if not all(isinstance(n, int) and not isinstance(n, bool) for n in segment):
            raise ValueError("Invalid word timing")
        if last != first + 1 or not 0 <= first < word_count or not 0 <= start < end:
            raise ValueError("Word timing cannot isolate the selected phrase")
        if first in timings:
            raise ValueError("Duplicate word timing")
        timings[first] = (start, end)
    if set(timings) != set(range(word_count)):
        raise ValueError("Reference word count and audio timings differ")
    ordered = tuple(timings[i] for i in range(word_count))
    if any(right[0] < left[0] or right[1] < left[1] for left, right in zip(ordered, ordered[1:])):
        raise ValueError("Reference timings are out of order")
    return url, ordered
