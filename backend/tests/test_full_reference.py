"""Full-corpus tests — run against data/quran_reference.json built by
scripts/build_reference.py (Tanzil Uthmani via AlQuran Cloud)."""
import pytest

from app.ai.reference import load_full_reference

try:
    REF = load_full_reference()
except FileNotFoundError:
    pytest.skip("full corpus not built yet", allow_module_level=True)


def test_corpus_totals():
    assert len(REF) == 114
    total_ayahs = sum(len(s) for s in REF.values())
    assert total_ayahs == 6236

def test_bismillah_handling():
    # Compare via normalized text: Tanzil-derived sources vary in
    # shadda/vowel codepoint order, which normalization removes.
    from app.ai.normalization import fix_whisper
    norm = lambda s, a: fix_whisper(REF[s][a]["text"])
    # Surah 1: Bismillah IS ayah 1
    assert norm(1, 1).startswith("بسم")
    # Surah 112 ayah 1: API prefix stripped, text starts with the ayah itself
    assert norm(112, 1).startswith("قل")
    assert REF[112][1]["word_count"] == 4
    # Surahs 95 & 97 (typo'd prefix in the API) also stripped
    assert norm(95, 1).startswith("والتين")
    assert norm(97, 1).startswith("انا")
    # Surah 9: no bismillah, ayah 1 is Bara'ah
    assert norm(9, 1).startswith("برا")

def test_ayat_al_kursi_present():
    assert REF[2][255]["word_count"] > 40
