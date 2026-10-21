"""Cases 44-50 from report §5.4. Cases 49 & 50 FAILED there (D02, D03);
both are fixed here with explicit, tested behaviour."""
import numpy as np

from app.ai.audio_guardrails import AudioStatus, validate_audio
from app.ai.pipeline import analyze_recitation
from app.ai.reference import load_sample_reference

REF = "بِسْمِ ٱللَّهِ ٱلرَّحْمَٰنِ ٱلرَّحِيمِ"  # 1:1


def test_44_perfect_recitation():
    r = analyze_recitation(REF, REF)
    assert r.status == "ok" and not r.has_mistakes

def test_45_skipped_word():
    r = analyze_recitation(REF, "بِسْمِ ٱللَّهِ ٱلرَّحِيمِ")
    assert r.status == "ok" and [s.index for s in r.skips] == [2]

def test_46_harakat_error():
    r = analyze_recitation(REF, "بَسْمِ ٱللَّهِ ٱلرَّحْمَٰنِ ٱلرَّحِيمِ")
    assert r.status == "ok" and len(r.harakat_errors) >= 1

def test_47_silent_input_rejected():
    assert validate_audio(np.zeros(16000)).status == AudioStatus.SILENCE_DETECTED
    r = analyze_recitation(REF, "")
    assert r.status == "rejected" and r.reason == "EMPTY_TRANSCRIPTION"

def test_48_normal_audio_passes_guardrails():
    rng = np.random.default_rng(7)
    assert validate_audio(rng.standard_normal(16000)).status == AudioStatus.NORMALIZED_SUCCESS

def test_49_empty_reference_FIXED():
    # Report D02: empty reference produced a 'Mismatch'. Now: explicit
    # rejection BEFORE scoring, with a machine-readable reason.
    r = analyze_recitation("", "بِسْمِ ٱللَّهِ")
    assert r.status == "rejected" and r.reason == "EMPTY_REFERENCE"
    assert not r.harakat_errors

def test_50_unvocalized_vs_vocalized_FIXED():
    # Report D03: same base words, vowel evidence missing on heard side.
    # Was 'Mismatch'/false pass. Now: UNCERTAIN — retry, don't confirm.
    r = analyze_recitation(REF, "بسم الله الرحمن الرحيم")
    assert r.status == "uncertain" and r.reason == "INSUFFICIENT_VOWEL_EVIDENCE"
    assert r.skips == []

def test_reference_loader_sample():
    ref = load_sample_reference()
    assert ref[1][1]["word_count"] == 4
    assert ref[112][1]["text"].startswith("قُلْ")
