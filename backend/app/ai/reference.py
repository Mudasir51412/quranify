"""
Quran reference loader — builds QURAN_REF[surah][ayah] as in the report:
diacritized text, diacritic-stripped word list, and word count.

Both representations are required: skip detection compares normalized
words; Harakat detection requires the vowel marks.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .normalization import fix_whisper


def build_reference(data: dict) -> dict:
    ref: dict[int, dict[int, dict]] = {}
    for surah_str, surah in data.get("surahs", {}).items():
        s = int(surah_str)
        ref[s] = {}
        for ayah_str, text in surah.get("ayahs", {}).items():
            a = int(ayah_str)
            stripped = fix_whisper(text).split()
            ref[s][a] = {
                "text": text,
                "words": stripped,
                "word_count": len(stripped),
            }
    return ref


def load_sample_reference(path: str | Path | None = None) -> dict:
    if path is None:
        # repo layout: backend/app/ai/reference.py -> ../../../data/sample_quran.json
        path = Path(__file__).resolve().parents[3] / "data" / "sample_quran.json"
    with open(path, encoding="utf-8") as f:
        return build_reference(json.load(f))


def load_full_reference(path: str | Path | None = None) -> dict:
    """Full 114-Surah corpus built by scripts/build_reference.py."""
    if path is None:
        path = Path(__file__).resolve().parents[3] / "data" / "quran_reference.json"
    with open(path, encoding="utf-8") as f:
        return build_reference(json.load(f))


@lru_cache(maxsize=2)
def _cached_reference(path: str, modified_ns: int, size: int) -> dict:
    """Shared read-only corpus; the file signature invalidates stale entries."""
    return load_full_reference(path)


def load_reference() -> dict:
    """Full corpus if built, otherwise the sample; reuse normalized word data."""
    full = Path(__file__).resolve().parents[3] / "data" / "quran_reference.json"
    path = full if full.exists() else full.with_name("sample_quran.json")
    info = path.stat()
    return _cached_reference(str(path), info.st_mtime_ns, info.st_size)
