"""Real-model practice smoke checks using professional reference audio only.

Tempo changes and repeated clips are synthetic test variations. These checks do
not validate learner pronunciation, physical-microphone capture or phone playback.
"""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def wav_bytes(samples):
    import numpy as np
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
    return output.getvalue()


def main():
    import httpx
    import numpy as np
    source = ROOT / "benchmarks/audio_cache/112001.wav"
    if not source.is_file():
        raise SystemExit("Cached 112:1 reference WAV is required")
    with tempfile.TemporaryDirectory(prefix="quranify-practice-") as folder:
        os.environ["DATABASE_URL"] = "sqlite:///" + (Path(folder) / "smoke.db").as_posix()
        from fastapi.testclient import TestClient
        from app.db import engine
        from app.main import app
        from app.routers.analyze import get_transcriber
        from app.services.transcriber import decode_audio

        results = []
        try:
            with TestClient(app) as client:
                auth = client.post("/auth/register", json={
                    "email": "practice-smoke@example.invalid", "password": "isolated-smoke-test"})
                auth.raise_for_status()
                headers = {"Authorization": "Bearer " + auth.json()["token"]}

                def upload(label, audio, **fields):
                    started = time.perf_counter()
                    response = client.post("/analyze", headers=headers,
                        data={"surah": 112, "ayah": 1, **fields},
                        files={"audio": ("practice.wav", audio, "audio/wav")})
                    response.raise_for_status()
                    body = response.json()
                    row = {"case": label, "seconds": round(time.perf_counter() - started, 3), **body}
                    results.append(row)
                    print(json.dumps({k: row[k] for k in ("case", "seconds", "status", "retry_words")}), flush=True)
                    assert not body["skips"] and not body["harakat_errors"] and not body["incorrect_words"], row
                    return body

                upload("professional_reference", source.read_bytes())
                slow = Path(folder) / "slow.wav"
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(source),
                    "-af", "atempo=0.65", "-ar", "16000", "-ac", "1", str(slow)], check=True)
                upload("synthetic_slow_tempo_0.65", slow.read_bytes())
                samples = decode_audio(source.read_bytes(), ".wav")
                upload("synthetic_ayah_restart", wav_bytes(np.concatenate([samples, np.zeros(3200), samples])))

                correction = client.get("/correction_audio", headers=headers,
                    params={"surah": 112, "ayah": 1, "word": 1, "word_start": 0, "word_end": 2})
                correction.raise_for_status()
                clip = correction.json()
                media = httpx.get(clip["audio_url"], timeout=20)
                media.raise_for_status()
                reference_samples = decode_audio(media.content, ".mp3")
                start, end = clip["start_ms"] * 16, clip["end_ms"] * 16
                assert 0 <= start < end <= len(reference_samples)
                phrase = upload("timed_reference_phrase_only", wav_bytes(reference_samples[start:end]),
                                word_start=0, word_end=2)
                assert phrase["status"] == "ok" and phrase["confirmed_words"] == [0, 1, 2]
                assert clip["start_ms"] > 0 and clip["end_ms"] < len(reference_samples) / 16

            model = get_transcriber()
            report = {"engine": model.engine, "device": model.device, "uploads": results,
                "phrase_playback": clip,
                "caveat": "Professional reference clips and synthetic tempo/restart variants; no learner microphone or physical-phone playback test."}
            (ROOT / "benchmarks/practice_feedback_smoke.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        finally:
            engine.dispose()


if __name__ == "__main__":
    main()
