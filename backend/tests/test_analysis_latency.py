import io
from pathlib import Path
import wave

import numpy as np
import pytest

from app.ai import reference
from app.services.transcriber import decode_audio


def wav(samples, *, channels=1, rate=16000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(np.asarray(samples, dtype="<i2").tobytes())
    return buf.getvalue()


def test_native_phone_wav_does_not_launch_a_converter(monkeypatch):
    def unwanted_converter(*args, **kwargs):
        pytest.fail("A native 16kHz mono PCM16 recording must not launch ffmpeg")
    monkeypatch.setattr("app.services.transcriber.subprocess.run", unwanted_converter)
    samples = np.array([-32768, -512, 0, 512, 32767], dtype="<i2")
    decoded = decode_audio(wav(samples), ".wav")
    np.testing.assert_array_equal(decoded, samples.astype(np.float32) / 32768.0)


def test_other_audio_formats_still_use_the_converter(monkeypatch):
    calls = []
    def convert(command, **kwargs):
        calls.append(command)
        Path(command[-1]).write_bytes(wav([512, -512]))
    monkeypatch.setattr("app.services.transcriber.subprocess.run", convert)
    decoded = decode_audio(wav([100, 200, 300, 400], channels=2, rate=44100), ".wav")
    np.testing.assert_array_equal(decoded, np.array([512, -512], dtype=np.float32) / 32768)
    assert len(calls) == 1


def test_truncated_pcm_is_rejected_before_inference():
    with pytest.raises(ValueError, match="Truncated PCM"):
        decode_audio(wav([512, -512])[:-1], ".wav")


def test_repeated_reference_requests_do_not_rebuild_the_corpus(monkeypatch):
    cache = getattr(reference, "_cached_reference", None)
    if cache:
        cache.cache_clear()
    calls = []
    def load(*args):
        calls.append(args)
        return {112: {1: {"text": "قُلْ هُوَ ٱللَّهُ أَحَدٌ"}}}
    monkeypatch.setattr(reference, "load_full_reference", load)
    try:
        assert reference.load_reference() == reference.load_reference()
        assert len(calls) == 1
    finally:
        if cache:
            cache.cache_clear()


def test_startup_warms_model_before_the_first_request(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.main import lifespan
    from app.config import settings
    from app.routers.analyze import get_transcriber

    calls = []
    class Model:
        engine = "test-engine"
        device = "auto"
        def warmup(self):
            calls.append("warm")
            return "cuda"
    local = FastAPI(lifespan=lifespan)
    local.dependency_overrides[get_transcriber] = lambda: Model()
    monkeypatch.setattr(settings, "warm_model_on_startup", True)
    @local.get("/ready")
    def ready():
        assert calls == ["warm"]
        return local.state.inference
    with TestClient(local) as client:
        assert client.get("/ready").json() == {"status": "ready", "engine": "test-engine", "device": "cuda"}


def test_failed_model_warmup_does_not_disable_other_api_routes(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.main import lifespan
    from app.config import settings
    from app.routers.analyze import get_transcriber

    class Model:
        def warmup(self):
            raise RuntimeError("Model not available")
    local = FastAPI(lifespan=lifespan)
    local.dependency_overrides[get_transcriber] = lambda: Model()
    monkeypatch.setattr(settings, "warm_model_on_startup", True)
    @local.get("/ready")
    def ready():
        return local.state.inference
    with TestClient(local) as client:
        assert client.get("/ready").json()["status"] == "unavailable"
