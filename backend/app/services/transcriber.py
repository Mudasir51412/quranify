"""
Transcription service — pluggable so the API (and its tests) never
depend on model-download state.

- WhisperTranscriber: real model (transformers, loaded by startup warmup
  or first use, from the local HF cache). Production target is faster-whisper;
  the interface is identical either way.
- FakeTranscriber: returns a caller-set transcription. Used by tests.
- decode_audio(): native phone WAVs decode directly in memory; other
  formats convert to 16kHz mono using ffmpeg. No extra decoding deps.
"""
from __future__ import annotations

import io
import subprocess
import tempfile
import wave
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np


@dataclass(frozen=True)
class SpokenWord:
    text: str
    start: float
    end: float


@dataclass(frozen=True)
class Recognition:
    text: str
    low_confidence_words: tuple[str, ...] = ()
    reliable: bool = True


class Transcriber(Protocol):
    def transcribe(self, audio: np.ndarray) -> str: ...


class FakeTranscriber:
    def __init__(self, text: str = ""):
        self.text = text

    def transcribe(self, audio: np.ndarray) -> str:
        return self.text


class WhisperTranscriber:
    engine = "transformers"
    def __init__(self, model_id: str, device: str = "auto"):
        self.model_id = model_id
        self._processor = None
        self._model = None
        self._pipe = None
        self.device = device
        self._lock = threading.RLock()

    def _load(self):
        if self._model is None:
            import torch
            from transformers import WhisperForConditionalGeneration, WhisperProcessor
            self._processor = WhisperProcessor.from_pretrained(self.model_id)
            if self.device == "auto":
                self.device = "cuda" if torch.cuda.is_available() else "cpu"
            if self.device == "cuda" and not torch.cuda.is_available():
                raise RuntimeError("CUDA requested, but install a CUDA-enabled PyTorch build first")
            dtype = torch.float16 if self.device == "cuda" else torch.float32
            model = WhisperForConditionalGeneration.from_pretrained(
                self.model_id, torch_dtype=dtype, attn_implementation="eager")
            model.to(self.device)
            self._model = model
            self._model.config.forced_decoder_ids = None
            self._model.eval()

    def transcribe(self, audio: np.ndarray) -> str:
        with self._lock:
            self._load()
            import torch
            inputs = self._processor(audio, return_tensors="pt", sampling_rate=16000)
            features = inputs["input_features"].to(self.device, dtype=self._model.dtype)
            with torch.inference_mode():
                ids = self._model.generate(features, language="ar", task="transcribe")
            return self._processor.batch_decode(ids, skip_special_tokens=True)[0].strip()

    def warmup(self) -> str:
        """Pay model/decoder initialization before accepting recitation uploads."""
        self.transcribe(np.zeros(16000, dtype=np.float32))
        return self.device

    def transcribe_for_review(self, audio: np.ndarray, *, verify: bool = False) -> Recognition:
        """Unprompted decodes: never supply the expected verse to the recognizer."""
        with self._lock:
            self._load()
            import torch
            inputs = self._processor(audio, return_tensors="pt", sampling_rate=16000)
            features = inputs["input_features"].to(self.device, dtype=self._model.dtype)
            with torch.inference_mode():
                output = self._model.generate(features, language="ar", task="transcribe",
                    num_beams=1 if verify else 5, return_dict_in_generate=True,
                    output_scores=True)
                scores = self._model.compute_transition_scores(output.sequences, output.scores,
                    getattr(output, "beam_indices", None), normalize_logits=True)
            text = self._processor.batch_decode(output.sequences, skip_special_tokens=True)[0].strip()
            # A conservative recognition gate, not a calibrated pronunciation score.
            reliable = bool(scores.numel()) and float(scores.exp().mean()) >= 0.4
            return Recognition(text, reliable=reliable)

    def prepare_stream(self) -> str:
        """Load before opening the microphone; timestamps safely retire old audio."""
        with self._lock:
            self._load()
            if self._pipe is None:
                from transformers import pipeline
                config = self._model.generation_config
                if not getattr(config, "alignment_heads", None):
                    # The fine-tuned small checkpoint predates this metadata.
                    # https://huggingface.co/openai/whisper-small/blob/main/generation_config.json
                    if self._model.config.decoder_layers != 12 or self._model.config.d_model != 768:
                        raise RuntimeError("Streaming requires alignment_heads for this checkpoint")
                    config.alignment_heads = [
                        [5, 3], [5, 9], [8, 0], [8, 4], [8, 7],
                        [8, 8], [9, 0], [9, 7], [9, 9], [10, 5]]
                self._pipe = pipeline(
                    "automatic-speech-recognition", model=self._model,
                    tokenizer=self._processor.tokenizer,
                    feature_extractor=self._processor.feature_extractor,
                    device=self.device)
            return self.device

    def transcribe_words(self, audio: np.ndarray) -> list[SpokenWord]:
        with self._lock:
            self.prepare_stream()
            duration = len(audio) / 16000
            result = self._pipe(
                {"array": audio, "sampling_rate": 16000},
                return_timestamps="word",
                generate_kwargs={"language": "ar", "task": "transcribe",
                                 "num_beams": 1,
                                 "no_repeat_ngram_size": 3,
                                 "max_new_tokens": max(24, min(128, int(duration * 16) + 8))})
            words = []
            for chunk in result.get("chunks", []):
                start, end = chunk["timestamp"]
                if start is None:
                    continue
                # An unfinished final word has no end timestamp: defer it.
                if end is None:
                    continue
                text = chunk["text"].strip()
                # Whisper can hallucinate a repeated tail on a partial word;
                # zero-duration words do not constitute acoustic evidence.
                if text and 0 <= start < end <= duration + 0.1 and end - start >= 0.04:
                    words.append(SpokenWord(text, float(start), min(float(end), duration)))
            return words


def decode_audio(raw_bytes: bytes, suffix: str = ".bin") -> np.ndarray:
    """Convert uploaded audio bytes to a 16kHz mono float32 array."""
    try:
        with wave.open(io.BytesIO(raw_bytes), "rb") as wav:
            if (wav.getnchannels() == 1 and wav.getsampwidth() == 2
                    and wav.getframerate() == 16000 and wav.getcomptype() == "NONE"):
                frames = wav.readframes(wav.getnframes())
                if len(frames) != wav.getnframes() * 2:
                    raise ValueError("Truncated PCM recording")
                return np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    except (wave.Error, EOFError):
        pass
    # Compressed audio and other WAV formats still require proper conversion.
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
