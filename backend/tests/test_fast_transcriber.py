import numpy as np
from types import SimpleNamespace

from app.services.fast_transcriber import FasterWhisperTranscriber


def test_full_ayah_uses_full_token_budget_while_live_windows_remain_bounded():
    class Model:
        def __init__(self):
            self.calls = []

        def transcribe(self, audio, **kwargs):
            self.calls.append(kwargs)
            return iter([]), None

    model = Model()
    transcriber = FasterWhisperTranscriber("unused", "cpu")
    transcriber._model = model
    audio = np.zeros(16000 * 30, dtype=np.float32)
    transcriber.transcribe(audio)
    transcriber.transcribe_words(audio)
    assert model.calls[0]["max_new_tokens"] is None
    assert model.calls[1]["max_new_tokens"] == 128


def test_review_discards_confident_zero_duration_hallucinations_without_suppressing_real_repeats():
    class Model:
        def transcribe(self, audio, **kwargs):
            assert kwargs["max_new_tokens"] == 36
            assert kwargs["no_repeat_ngram_size"] == 0
            word = lambda text, start, end: SimpleNamespace(word=text, start=start, end=end, probability=0.99)
            segment = SimpleNamespace(avg_logprob=-0.1, no_speech_prob=0.0,
                words=[word("قُلْ", 0, 0.2), word("قُلْ", 0.3, 0.5), word("الرَّحْمَنُ", 0.5, 0.5)])
            return iter([segment]), None
    transcriber = FasterWhisperTranscriber("unused", "cpu")
    transcriber._model = Model()
    result = transcriber.transcribe_for_review(np.zeros(16000, dtype=np.float32))
    assert result.text == "قُلْ قُلْ"
    assert result.low_confidence_words == ("الرَّحْمَنُ",)
