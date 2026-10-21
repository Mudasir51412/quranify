#!/usr/bin/env python3
"""
Benchmark v0 — basharalrfooh/whisper-small-quran (transformers, CPU).

Samples: EveryAyah per-Ayah MP3s, reciter Mishary Rashid Alafasy
(128kbps), for a fixed set of short Ayahs. Ground truth = our own
Tanzil corpus (data/quran_reference.json).

⚠️ CAVEAT (stated in results too): EveryAyah is this model's stated
training distribution, so this is an in-distribution SMOKE benchmark:
it validates the end-to-end pipeline and the model's output format
(does it emit diacritics?). It is NOT a held-out generalization number.
The held-out benchmark (Buraaq reciters / real user recordings) is
benchmark v1.

Metrics: WER + CER, computed both RAW (as transcribed) and NORMALIZED
(after fix_whisper, which is the space our alignment pipeline works in).
Each transcription is also fed through analyze_recitation() and the
pipeline verdict recorded.

Usage: python scripts/benchmark_model.py [--limit N]
Outputs: benchmarks/v0_everyayah_smoke.json + .md
"""
import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.ai.normalization import fix_whisper  # noqa: E402
from app.ai.pipeline import analyze_recitation  # noqa: E402
from app.ai.reference import load_full_reference  # noqa: E402

MODEL_ID = "basharalrfooh/whisper-small-quran"
EVERYAYAH = "https://everyayah.com/data/Alafasy_128kbps/{s:03d}{a:03d}.mp3"
SAMPLES = [(112, 1), (112, 2), (112, 3), (112, 4), (113, 1),
           (114, 1), (114, 6), (1, 1), (1, 2), (108, 1)]


def edit_distance(a: list, b: list) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def wer(ref: str, hyp: str) -> float:
    r, h = ref.split(), hyp.split()
    return edit_distance(r, h) / max(len(r), 1)


def cer(ref: str, hyp: str) -> float:
    r, h = list(ref.replace(" ", "")), list(hyp.replace(" ", ""))
    return edit_distance(r, h) / max(len(r), 1)


def fetch_audio(surah: int, ayah: int, cache: Path) -> np.ndarray:
    mp3 = cache / f"{surah:03d}{ayah:03d}.mp3"
    wav = cache / f"{surah:03d}{ayah:03d}.wav"
    if not wav.exists():
        if not mp3.exists():
            req = urllib.request.Request(EVERYAYAH.format(s=surah, a=ayah),
                                         headers={"User-Agent": "quranify-mvp/0.1"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                mp3.write_bytes(resp.read())
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3),
                        "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(wav)],
                       check=True)
    import wave
    with wave.open(str(wav)) as w:
        frames = w.readframes(w.getnframes())
    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=len(SAMPLES))
    args = ap.parse_args()
    samples = SAMPLES[: args.limit]

    cache = ROOT / "benchmarks" / "audio_cache"
    cache.mkdir(parents=True, exist_ok=True)
    outdir = ROOT / "benchmarks"
    ref = load_full_reference()

    print(f"Loading model {MODEL_ID} (CPU) ...", flush=True)
    import torch
    from transformers import WhisperForConditionalGeneration, WhisperProcessor
    t0 = time.time()
    processor = WhisperProcessor.from_pretrained(MODEL_ID)
    model = WhisperForConditionalGeneration.from_pretrained(MODEL_ID)
    model.config.forced_decoder_ids = None
    model.eval()
    print(f"Model loaded in {time.time()-t0:.0f}s", flush=True)

    rows = []
    for (s, a) in samples:
        reference = ref[s][a]["text"]
        audio = fetch_audio(s, a, cache)
        inputs = processor(audio, return_tensors="pt", sampling_rate=16000)
        t1 = time.time()
        with torch.no_grad():
            ids = model.generate(inputs["input_features"], language="ar", task="transcribe")
        infer_s = time.time() - t1
        hyp = processor.batch_decode(ids, skip_special_tokens=True)[0].strip()
        result = analyze_recitation(reference, hyp)
        row = {
            "surah": s, "ayah": a,
            "audio_seconds": round(len(audio) / 16000, 2),
            "inference_seconds": round(infer_s, 2),
            "reference": reference,
            "transcription": hyp,
            "wer_raw": round(wer(reference, hyp), 4),
            "cer_raw": round(cer(reference, hyp), 4),
            "wer_normalized": round(wer(fix_whisper(reference), fix_whisper(hyp)), 4),
            "cer_normalized": round(cer(fix_whisper(reference), fix_whisper(hyp)), 4),
            "transcription_has_diacritics": any("\u064B" <= c <= "\u0652" for c in hyp),
            "pipeline_status": result.status,
            "pipeline_skips": [sk.index for sk in result.skips],
            "pipeline_harakat_errors": len(result.harakat_errors),
        }
        rows.append(row)
        print(f"{s}:{a}  WERn={row['wer_normalized']:.2f}  CERn={row['cer_normalized']:.2f}  "
              f"diacritics={row['transcription_has_diacritics']}  pipeline={result.status} "
              f"skips={row['pipeline_skips']} harakat={row['pipeline_harakat_errors']} "
              f"({infer_s:.1f}s)", flush=True)

    def avg(k): return round(sum(r[k] for r in rows) / max(len(rows), 1), 4)
    summary = {
        "model": MODEL_ID, "engine": "transformers (PyTorch, CPU)", "n": len(rows),
        "caveat": "In-distribution smoke benchmark (EveryAyah = model's training distribution). Not a held-out generalization estimate.",
        "reciter": "Mishary Rashid Alafasy (EveryAyah 128kbps)",
        "wer_raw": avg("wer_raw"), "cer_raw": avg("cer_raw"),
        "wer_normalized": avg("wer_normalized"), "cer_normalized": avg("cer_normalized"),
        "rows": rows,
    }
    (outdir / "v0_everyayah_smoke.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Benchmark v0 — EveryAyah smoke test",
        f"Model: `{MODEL_ID}` via transformers on CPU. n={len(rows)}.",
        f"**WER raw {summary['wer_raw']:.1%} · CER raw {summary['cer_raw']:.1%} · "
        f"WER normalized {summary['wer_normalized']:.1%} · CER normalized {summary['cer_normalized']:.1%}**",
        "", f"⚠️ {summary['caveat']}", "",
        "| Ayah | WER (norm) | CER (norm) | Diacritics in output | Pipeline | Skips | Harakat errs |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| {r['surah']}:{r['ayah']} | {r['wer_normalized']:.2f} | {r['cer_normalized']:.2f} "
                     f"| {r['transcription_has_diacritics']} | {r['pipeline_status']} "
                     f"| {r['pipeline_skips']} | {r['pipeline_harakat_errors']} |")
    (outdir / "v0_everyayah_smoke.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\nSUMMARY:", {k: summary[k] for k in ("n", "wer_raw", "cer_raw", "wer_normalized", "cer_normalized")})
    return 0


if __name__ == "__main__":
    sys.exit(main())
