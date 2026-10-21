"""Cases 37-43 from report §5.1.4 — all passed there; must stay green."""
import numpy as np

from app.ai.audio_guardrails import AudioStatus, validate_audio


def test_37_none_input():
    assert validate_audio(None).status == AudioStatus.NONE_AUDIO

def test_38_empty_array():
    assert validate_audio([]).status == AudioStatus.EMPTY_AUDIO

def test_39_silence():
    assert validate_audio(np.zeros(16000)).status == AudioStatus.SILENCE_DETECTED

def test_40_low_noise_is_silence():
    assert validate_audio(np.full(16000, 1e-6)).status == AudioStatus.SILENCE_DETECTED

def test_41_normal_signal_normalized():
    rng = np.random.default_rng(42)
    result = validate_audio(rng.standard_normal(16000))
    assert result.status == AudioStatus.NORMALIZED_SUCCESS
    assert abs(np.max(np.abs(result.audio)) - 1.0) < 1e-5

def test_42_nan_values():
    arr = np.ones(100); arr[5] = np.nan
    assert validate_audio(arr).status == AudioStatus.INVALID_VALUES

def test_43_infinite_values():
    arr = np.ones(100); arr[5] = np.inf
    assert validate_audio(arr).status == AudioStatus.INVALID_VALUES
