"""Measure timestamped streaming inference on real, cached recitation audio.

This is a model smoke test, not a held-out pronunciation accuracy benchmark.
Run from the repo root with backend/.venv/Scripts/python.exe.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import wave

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.ai.live import LiveRecitation, StableWords
from app.ai.reference import load_reference
from app.services.transcriber import WhisperTranscriber


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    args = parser.parse_args()
    cache = ROOT / "benchmarks" / "audio_cache"
    cache.mkdir(exist_ok=True)
    mp3, wav = cache / "112001.mp3", cache / "112001.wav"
    if not mp3.exists():
        request = urllib.request.Request(
            "https://everyayah.com/data/Alafasy_128kbps/112001.mp3",
            headers={"User-Agent": "quranify-live-smoke/1.0"})
        with urllib.request.urlopen(request, timeout=60) as response:
            mp3.write_bytes(response.read())
    if not wav.exists():
        subprocess.run([args.ffmpeg, "-y", "-loglevel", "error", "-i", str(mp3),
                        "-ar", "16000", "-ac", "1", str(wav)], check=True)
    with wave.open(str(wav)) as source:
        audio = np.frombuffer(source.readframes(source.getnframes()), dtype="<i2").astype(np.float32) / 32768
    model = WhisperTranscriber("basharalrfooh/whisper-small-quran", args.device)
    started = time.perf_counter()
    model.prepare_stream()
    print(f"Loaded on {model.device} in {time.perf_counter() - started:.1f}s", flush=True)
    reference = load_reference()
    tracker = LiveRecitation({a: row["text"] for a, row in reference[112].items()})
    stable = StableWords()
    rows = []
    for seconds in [1.0, 1.5, 2.0, 2.5, len(audio) / 16000, len(audio) / 16000]:
        clip = audio[:int(seconds * 16000)]
        started = time.perf_counter()
        words = model.transcribe_words(clip)
        elapsed = time.perf_counter() - started
        committed = stable.update(words)
        tracker.accept([w.text for w in committed])
        row = {"audio_seconds": seconds, "inference_seconds": round(elapsed, 3),
               "words": [{"text": w.text, "start": w.start, "end": w.end} for w in words],
               "committed": [w.text for w in committed], "scored_words": tracker.cursor}
        rows.append(row)
        print(json.dumps(row, ensure_ascii=True), flush=True)
    result = {"device": model.device, "caveat": "EveryAyah training-distribution smoke test; no physical-phone rehearsal",
              "rows": rows, "review": tracker.snapshot()}
    output = ROOT / "benchmarks" / f"live_{model.device}_smoke.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {output}", flush=True)


if __name__ == "__main__":
    main()
