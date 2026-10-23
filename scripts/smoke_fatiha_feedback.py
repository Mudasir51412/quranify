"""Real ASR checks on public Al-Fatiha audio and synthetic word edits.

Edited professional audio is a regression probe, not a learner accuracy study.
Report ASR hallucinations honestly rather than claiming text tests prove hearing.
"""
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main():
    import httpx
    import numpy as np
    from app.ai.practice import assess_practice
    from app.ai.reference import load_reference
    from app.services.fast_transcriber import FasterWhisperTranscriber
    from app.services.reference_audio import verse_audio
    from app.services.transcriber import Recognition, decode_audio

    ref = load_reference()[1]
    model = FasterWhisperTranscriber(str(ROOT / "models/whisper-small-quran-ct2"))
    model.warmup()
    cache = ROOT / "benchmarks/audio_cache"
    cache.mkdir(exist_ok=True)
    rows = []
    for ayah, removed in [(5, 1), (6, 1), (7, 6)]:
        text = ref[ayah]["text"]
        words = text.split()
        url, timings = verse_audio(1, ayah, len(words))
        path = cache / f"fatiha-001{ayah:03d}.mp3"
        if not path.is_file():
            response = httpx.get(url, timeout=20)
            response.raise_for_status()
            path.write_bytes(response.content)
        samples = decode_audio(path.read_bytes(), ".mp3")
        begin, end = timings[removed][0] * 16, timings[removed][1] * 16
        cases = [("reference", samples, None),
                 ("synthetic_word_omission", np.concatenate([samples[:begin], samples[end:]]), removed)]
        if ayah == 5:
            replacement = samples[timings[3][0] * 16:timings[3][1] * 16]
            cases.append(("synthetic_word_substitution", np.concatenate([
                samples[:begin], replacement, samples[end:]]), removed))
        for label, audio, target in cases:
            started = time.perf_counter()
            transcription = model.transcribe(audio)
            feedback = assess_practice(text, Recognition(transcription))
            row = {"ayah": ayah, "case": label, "target_word_index": target,
                "target_word": words[target] if target is not None else None,
                "seconds": round(time.perf_counter() - started, 3),
                "transcription": transcription, "states": feedback.states,
                "mistakes": feedback.mistakes,
                "edit_detected": target in feedback.mistakes if target is not None else None}
            rows.append(row)
            print(json.dumps({k: row[k] for k in ("ayah", "case", "seconds", "states", "edit_detected")}), flush=True)
            if target is not None:
                assert row["edit_detected"], "The deliberately edited word was accepted"
            else:
                assert not feedback.mistakes, "Reference audio received a false error label"
    report = {"engine": model.engine, "device": model.device, "cases": rows,
        "caveat": "Professional Al-Fatiha clips and synthetic edits; no validation of the user's microphone or pronunciation. The recognizer may still reconstruct unheard text."}
    (ROOT / "benchmarks/fatiha_feedback_smoke.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
