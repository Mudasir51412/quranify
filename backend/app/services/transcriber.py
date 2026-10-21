"""
Transcription service — pluggable so the API (and its tests) never
depend on model-download state.

- WhisperTranscriber: real model (transformers, lazy-loaded on first
  use, from the local HF cache). Production target is faster-whisper;
  the interface is identical either way.
- FakeTranscriber: returns a caller-set transcription. Used by tests.
- decode_audio(): any uploaded audio -> 16kHz mono float array via
  ffmpeg (system binary), then stdlib wave parsing. No extra deps.
"""
from __future__ import annotations

import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Protocol

import numpy as np


class Transcriber(Protocol):
    def transcribe(self, audio: np.ndarray) -> str: ...


class FakeTranscriber:
    def __init__(self, text: str = ""):
        self.text = text

    def transcribe(self, audio: np.ndarray) -> str:
        return self.text


class WhisperTranscriber:
    def __init__(self, model_id: str):
        self.model_id = model_id
        self._processor = None
        self._model = None

    def _load(self):
        if self._model is None:
            import torch  # noqa: F401  (kept loaded for generate)
            from transformers import WhisperForConditionalGeneration, WhisperProcessor
            self._processor = WhisperProcessor.from_pretrained(self.model_id)
            self._model = WhisperForConditionalGeneration.from_pretrained(self.model_id)
            self._model.config.forced_decoder_ids = None
            self._model.eval()

    def transcribe(self, audio: np.ndarray) -> str:
        self._load()
        import torch
        inputs = self._processor(audio, return_tensors="pt", sampling_rate=16000)
        with torch.no_grad():
            ids = self._model.generate(
                inputs["input_features"], language="ar", task="transcribe")
        return self._processor.batch_decode(ids, skip_special_tokens=True)[0].strip()


def decode_audio(raw_bytes: bytes, suffix: str = ".bin") -> np.ndarray:
    """Convert uploaded audio bytes to a 16kHz mono float32 array."""
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / f"in{suffix}"
        dst = Path(td) / "out.wav"
        src.write_bytes(raw_bytes)
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
             "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(dst)],
            check=True, capture_output=True, timeout=60)
        with wave.open(str(dst)) as w:
            frames = w.readframes(w.getnframes())
    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
