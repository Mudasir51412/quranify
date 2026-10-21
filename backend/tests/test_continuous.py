"""AI-level tests for Huffaz continuous mode (ai/continuous.py)."""
import json
from pathlib import Path

from app.ai.continuous import analyze_continuous

DATA = json.loads((Path(__file__).resolve().parents[2] / "data" / "sample_quran.json")
                  .read_text(encoding="utf-8"))
AYAHS = DATA["surahs"]["112"]["ayahs"]
WINDOW = {int(k): v for k, v in AYAHS.items()}


def test_full_window_perfect():
    text = " ".join(WINDOW[a] for a in (1, 2, 3, 4))
    r = analyze_continuous(WINDOW, text)
    assert r.status == "ok" and r.skips == [] and r.skipped_ayahs == []
    assert r.confirmed_ayah == 4

def test_skipped_middle_ayah():
    r = analyze_continuous(WINDOW, WINDOW[1] + " " + WINDOW[3])
    assert r.skipped_ayahs == [2]
    assert all(s.ayah == 2 for s in r.skips)
    assert r.confirmed_ayah == 3

def test_tail_unscored():
    r = analyze_continuous(WINDOW, WINDOW[1])
    assert r.status == "ok" and r.skips == []
    assert r.scored_words == 4 and r.confirmed_ayah == 1 and r.confirmed_word_index == 3

def test_no_match():
    r = analyze_continuous(WINDOW, "ذهب خالد الى السوق صباحا")
    assert r.status == "no_match"

def test_harakat_error_in_continuous():
    bad = WINDOW[1].replace("قُلْ", "قَلْ", 1)  # damma -> fatha on ق
    r = analyze_continuous({1: WINDOW[1]}, bad)
    assert r.status == "ok"
    assert any(e["expected_vowel"] == "damma" and e["heard_vowel"] == "fatha"
               for e in r.harakat_errors)
