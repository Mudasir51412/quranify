"""
Audio guardrails (report §5.1.4) — reject unusable audio BEFORE the
model ever sees it, and peak-normalize valid audio.

Statuses (names preserved from the report's test log):
  NONE_AUDIO, EMPTY_AUDIO, SILENCE_DETECTED, INVALID_VALUES,
  NORMALIZED_SUCCESS
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np


class AudioStatus(str, Enum):
    NONE_AUDIO = "NONE_AUDIO"
    EMPTY_AUDIO = "EMPTY_AUDIO"
    SILENCE_DETECTED = "SILENCE_DETECTED"
    INVALID_VALUES = "INVALID_VALUES"
    NORMALIZED_SUCCESS = "NORMALIZED_SUCCESS"


@dataclass
class AudioValidation:
    status: AudioStatus
    audio: np.ndarray | None = None  # normalized audio when SUCCESS


_SILENCE_PEAK = 1e-4


def validate_audio(audio) -> AudioValidation:
    if audio is None:
        return AudioValidation(AudioStatus.NONE_AUDIO)
    arr = np.asarray(audio, dtype=np.float64)
    if arr.size == 0:
        return AudioValidation(AudioStatus.EMPTY_AUDIO)
    if not np.all(np.isfinite(arr)):
        return AudioValidation(AudioStatus.INVALID_VALUES)
    peak = np.max(np.abs(arr)) if arr.size else 0.0
    if peak <= _SILENCE_PEAK:
        return AudioValidation(AudioStatus.SILENCE_DETECTED)
    normalized = (arr / peak).astype(np.float32)
    return AudioValidation(AudioStatus.NORMALIZED_SUCCESS, audio=normalized)
