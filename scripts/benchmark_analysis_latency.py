"""Profile cold/warm uploads with an isolated DB and cached reference audio.

Server-side in-process timings exclude phone capture, upload and physical Wi-Fi.
"""
import argparse
import json
import os
from pathlib import Path
import statistics
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="benchmarks/analysis_latency_baseline.json")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="quranify-latency-") as folder:
        os.environ["DATABASE_URL"] = "sqlite:///" + (Path(folder) / "latency.db").as_posix()
        from fastapi.testclient import TestClient
        from app.db import engine
        from app.main import app
        from app.routers import analyze as route

        phases = {}
        originals = {}
        def timed(owner, name, label):
            original = getattr(owner, name)
            originals[(owner, name)] = original
            def call(*a, **kw):
                started = time.perf_counter()
                try:
                    return original(*a, **kw)
                finally:
                    phases.setdefault(label, []).append(time.perf_counter() - started)
            setattr(owner, name, call)

        timed(route, "load_reference", "reference")
        timed(route, "decode_audio", "audio_decode")
        model = route.get_transcriber()
        timed(model, "transcribe", "recognition")
        rows = []
        try:
            startup_started = time.perf_counter()
            with TestClient(app) as client:
                startup_ms = round((time.perf_counter() - startup_started) * 1000, 1)
                auth = client.post("/auth/register", json={
                    "email": "latency@example.invalid", "password": "isolated-latency-test"})
                auth.raise_for_status()
                headers = {"Authorization": "Bearer " + auth.json()["token"]}
                for attempt, ayah in enumerate([1, 1, 2, 3, 4, 1, 3, 4]):
                    clip = ROOT / "benchmarks/audio_cache" / f"112{ayah:03d}.wav"
                    phases.clear()
                    started = time.perf_counter()
                    result = client.post("/analyze", headers=headers,
                        data={"surah": 112, "ayah": ayah},
                        files={"audio": ("reference.wav", clip.read_bytes(), "audio/wav")})
                    elapsed = time.perf_counter() - started
                    result.raise_for_status()
                    body = result.json()
                    row = {"attempt": attempt, "ayah": ayah, "total_ms": round(elapsed * 1000, 1),
                        "phases_ms": {k: [round(v * 1000, 1) for v in values] for k, values in phases.items()},
                        "status": body["status"], "transcription": body["transcription"],
                        "retry_words": body["retry_words"], "skips": body["skips"],
                        "harakat_errors": body["harakat_errors"], "incorrect_words": body["incorrect_words"]}
                    rows.append(row)
                    print(json.dumps({k: row[k] for k in ("attempt", "ayah", "total_ms", "phases_ms", "status")}), flush=True)
            report = {"engine": model.engine, "device": model.device,
                "startup_ms": startup_ms, "first_request_ms": rows[0]["total_ms"],
                "warm_median_ms": round(statistics.median(r["total_ms"] for r in rows[1:]), 1),
                "warm_max_ms": max(r["total_ms"] for r in rows[1:]), "attempts": rows,
                "caveat": "Server-side reference-audio benchmark, excludes phone recording and Wi-Fi upload; no learner accuracy validation."}
            (ROOT / args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        finally:
            for (owner, name), original in originals.items():
                setattr(owner, name, original)
            engine.dispose()


if __name__ == "__main__":
    main()
