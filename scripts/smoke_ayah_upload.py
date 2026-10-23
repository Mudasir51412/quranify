"""Exercise a real single-Ayah WAV upload/model against an isolated database.

Uses cached reference audio from the earlier benchmark. This checks the upload
pipeline, not learner pronunciation accuracy or the physical phone microphone.
"""
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main():
    clips = [ROOT / "benchmarks" / "audio_cache" / f"112{ayah:03d}.wav"
             for ayah in (1, 2)]
    if not all(clip.is_file() for clip in clips):
        raise SystemExit("Cached 112:1 and 112:2 reference WAVs are required")

    with tempfile.TemporaryDirectory(prefix="quranify-ayah-") as folder:
        os.environ["DATABASE_URL"] = "sqlite:///" + (Path(folder) / "smoke.db").as_posix()
        from fastapi.testclient import TestClient
        from app.db import engine
        from app.main import app
        from app.routers.analyze import get_transcriber

        results = []
        try:
            with TestClient(app) as client:
                auth = client.post("/auth/register", json={
                    "email": "ayah-smoke@example.invalid", "password": "isolated-smoke-test"})
                auth.raise_for_status()
                headers = {"Authorization": "Bearer " + auth.json()["token"]}
                for ayah, clip in enumerate(clips, 1):
                    started = time.perf_counter()
                    response = client.post("/analyze", headers=headers,
                        data={"surah": 112, "ayah": ayah},
                        files={"audio": ("rec.wav", clip.read_bytes(), "audio/wav")})
                    elapsed = round(time.perf_counter() - started, 3)
                    response.raise_for_status()
                    body = response.json()
                    assert body["session_id"] is not None, body
                    assert body["transcription"], body
                    assert body["status"] in ("ok", "uncertain"), body
                    detail = client.get(f"/history/{body['session_id']}", headers=headers).json()
                    assert detail["surah"] == 112 and detail["ayah"] == ayah, detail
                    results.append({"surah": 112, "ayah": ayah, "seconds": elapsed,
                        **{k: body[k] for k in ("status", "transcription", "reference", "skips", "harakat_errors")}})

                silence = io.BytesIO()
                with wave.open(silence, "wb") as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(16000)
                    wav.writeframes(bytes(16000 * 2))
                response = client.post("/analyze", headers=headers,
                    data={"surah": 112, "ayah": 1},
                    files={"audio": ("silence.wav", silence.getvalue(), "audio/wav")})
                assert response.status_code == 400, response.text
                assert "SILENCE_DETECTED" in response.text, response.text
                assert len(client.get("/history", headers=headers).json()["sessions"]) == 2

            model = get_transcriber()
            report = {"engine": model.engine, "device": model.device, "uploads": results,
                "silence_rejected_without_session": True,
                "caveat": "Cached professional reference audio, isolated DB; physical microphone and learner accuracy untested"}
            (ROOT / "benchmarks" / "ayah_upload_smoke.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({"engine": report["engine"], "device": report["device"],
                "uploads": [{k: row[k] for k in ("surah", "ayah", "seconds", "status")}
                            for row in results],
                "silence_rejected_without_session": True}), flush=True)
        finally:
            engine.dispose()


if __name__ == "__main__":
    main()
