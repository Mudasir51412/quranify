"""CTranslate2 inference for the same Quran checkpoint, optimized for live use."""
import os
from pathlib import Path
import threading

import numpy as np

from .transcriber import Recognition, SpokenWord


class FasterWhisperTranscriber:
    engine = "faster-whisper"
    def __init__(self, model_dir: str, device: str = "auto"):
        self.model_dir = model_dir
        self.device = device
        self._model = None
        self._lock = threading.RLock()
        self._dll_handles = []

    def prepare_stream(self) -> str:
        with self._lock:
            if self._model is None:
                import torch
                if self.device == "auto":
                    self.device = "cuda" if torch.cuda.is_available() else "cpu"
                # CUDA PyTorch already ships the cuBLAS/cuDNN runtime. Make its
                # DLLs available to CTranslate2 as well on Windows.
                if os.name == "nt" and self.device == "cuda":
                    library = str(Path(torch.__file__).parent / "lib")
                    self._dll_handles.append(os.add_dll_directory(library))
                    os.environ["PATH"] = library + os.pathsep + os.environ.get("PATH", "")
                from faster_whisper import WhisperModel
                self._model = WhisperModel(
                    self.model_dir, device=self.device,
                    compute_type="float16" if self.device == "cuda" else "int8",
                    local_files_only=True)
            return self.device

    def _segments(self, audio: np.ndarray, word_timestamps: bool, *, review: bool = False,
                  verify: bool = False):
        self.prepare_stream()
        segments, _ = self._model.transcribe(
            audio, language="ar", beam_size=5 if review and not verify else 1, temperature=0.0,
            word_timestamps=word_timestamps, condition_on_previous_text=False,
            no_repeat_ngram_size=0 if review else 3,
            # Review permits repeats but bounds hallucinated tails on very
            # short phrases. Long clips retain the full segment token budget.
            max_new_tokens=(max(32, min(448, int(len(audio) / 16000 * 20) + 16)) if review else
                            max(24, min(128, int(len(audio) / 16000 * 16) + 8))
                            if word_timestamps else None),
        )
        return list(segments)

    def transcribe(self, audio: np.ndarray) -> str:
        with self._lock:
            return " ".join(s.text.strip() for s in self._segments(audio, False)).strip()

    def warmup(self) -> str:
        """Warm the original decoder used by recitation uploads."""
        self.transcribe(np.zeros(16000, dtype=np.float32))
        return self.device

    def transcribe_for_review(self, audio: np.ndarray, *, verify: bool = False) -> Recognition:
        with self._lock:
            segments = self._segments(audio, True, review=True, verify=verify)
            duration = len(audio) / 16000
            words = [w for s in segments for w in s.words or []]
            def supported(w):
                return 0 <= w.start < w.end <= duration + 0.1 and w.end - w.start >= 0.04
            # The fine-tuned model can append very confident, zero-duration
            # words after a short phrase. They are not acoustic observations.
            text = " ".join(w.word.strip() for w in words if supported(w)).strip()
            low = tuple(w.word.strip() for w in words if w.probability < 0.65 or not supported(w))
            reliable = bool(text) and all(s.avg_logprob >= -0.9 and s.no_speech_prob < 0.6
                                             for s in segments)
            return Recognition(text, low, reliable)

    def transcribe_words(self, audio: np.ndarray) -> list[SpokenWord]:
        with self._lock:
            duration = len(audio) / 16000
            return [SpokenWord(w.word.strip(), w.start, min(w.end, duration))
                    for segment in self._segments(audio, True) for w in segment.words or []
                    if w.word.strip() and 0 <= w.start < w.end <= duration + 0.1
                    and w.end - w.start >= 0.04]
