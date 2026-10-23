"""
POST /analyze — the core endpoint (report Table 4.6).

Flow: auth -> validate surah/ayah -> decode audio -> guardrails
(reject BEFORE scoring, no session saved for invalid audio) ->
transcribe -> AI pipeline -> persist session + mistakes -> respond.

GET /correction_audio returns a reference URL with verified word-boundary
start/end times for the selected phrase. Missing timings are a retryable
service error; the client must never fall back to whole-ayah playback.
"""
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..ai.audio_guardrails import AudioStatus, validate_audio
from ..ai.practice import assess_practice
from ..ai.reference import load_reference
from ..db import get_db
from ..models import MistakeRecord, RecitationSession, User
from ..security import get_current_user
from ..services.transcriber import Recognition, Transcriber, decode_audio
from ..services.reference_audio import verse_audio

router = APIRouter(tags=["analyze"])

_transcriber: Transcriber | None = None


def set_transcriber(t: Transcriber) -> None:
    global _transcriber
    _transcriber = t


def get_transcriber() -> Transcriber:
    global _transcriber
    if _transcriber is None:
        from ..config import settings
        from ..services.transcriber import WhisperTranscriber
        optimized = Path(settings.optimized_model_dir) / "model.bin"
        if settings.inference_engine == "faster-whisper" or (
            settings.inference_engine == "auto" and optimized.is_file()
            and (optimized.parent / ".ready").is_file()
        ):
            from ..services.fast_transcriber import FasterWhisperTranscriber
            _transcriber = FasterWhisperTranscriber(settings.optimized_model_dir, settings.inference_device)
        else:
            _transcriber = WhisperTranscriber(settings.model_id, settings.inference_device)
    return _transcriber


@router.post("/analyze")
async def analyze(
    surah: int = Form(...),
    ayah: int = Form(...),
    audio: UploadFile = File(...),
    word_start: int = Form(0),
    word_end: int | None = Form(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    transcriber: Transcriber = Depends(get_transcriber),
):
    ref = load_reference()
    if surah not in ref or ayah not in ref.get(surah, {}):
        raise HTTPException(400, "Unknown surah/ayah")
    reference_text = ref[surah][ayah]["text"]
    ref_words = reference_text.split()
    word_end = len(ref_words) - 1 if word_end is None else word_end
    if not 0 <= word_start <= word_end < len(ref_words):
        raise HTTPException(400, "Invalid phrase word range (zero-based, inclusive)")
    phrase = " ".join(ref_words[word_start:word_end + 1])

    raw = await audio.read()
    if not raw:
        raise HTTPException(400, "Empty audio upload")
    suffix = Path(audio.filename or "audio").suffix or ".bin"
    try:
        samples = decode_audio(raw, suffix=suffix)
    except Exception:
        raise HTTPException(400, "Could not decode audio file")

    guard = validate_audio(samples)
    if guard.status != AudioStatus.NORMALIZED_SUCCESS:
        # R1: reject before scoring; nothing is persisted.
        raise HTTPException(400, f"Audio rejected: {guard.status.value}")
    try:
        # Restore the original unprompted decoder. Another decode must not
        # fill omitted words or clear errors observed in this transcription.
        recognition = Recognition(transcriber.transcribe(guard.audio))
    except Exception:
        raise HTTPException(503, "Transcription service unavailable")

    result = assess_practice(phrase, recognition)
    status = "retry" if result.retry_words else "ok"
    skips, harakat_errors, incorrect = [], [], []
    for index, mistake in sorted(result.mistakes.items()):
        wi = word_start + index
        item = {"word_index": wi, "word": ref_words[wi], "ayah": ayah}
        if mistake["type"] == "skipped":
            skips.append({**item, "index": wi})
        elif mistake.get("reason") == "harakat":
            harakat_errors.extend({**item, **e} for e in mistake["harakat_errors"])
        else:
            incorrect.append({**item, "type": "incorrect"})
    confirmed = [word_start + i for i, state in enumerate(result.states) if state != "retry"]
    session = None
    if confirmed:
        session = RecitationSession(
            user_id=user.id, surah=surah, ayah=ayah, transcription=recognition.text,
            status=status, mode="single" if word_start == 0 and word_end == len(ref_words) - 1 else "phrase",
            total_words=len(confirmed), correct_words=result.states.count("matched"))
        db.add(session)
        db.flush()
        for kind, entries in (("skipped", skips), ("harakat", harakat_errors), ("incorrect", incorrect)):
            for item in entries:
                db.add(MistakeRecord(session_id=session.id, type=kind, ayah=ayah,
                    word_index=item["word_index"], reference_word=item["word"],
                    letter=item.get("letter", ""), expected_vowel=item.get("expected_vowel") or "",
                    heard_vowel=item.get("heard_vowel") or ""))
        db.commit()
    return {
        "session_id": session.id if session else None, "status": status,
        "reason": "RETRY_PHRASE" if result.retry_words else None,
        "transcription": recognition.text, "reference": reference_text,
        "total_words": len(confirmed), "word_start": word_start, "word_end": word_end,
        "confirmed_words": confirmed,
        "retry_words": [word_start + i for i in result.retry_words],
        "skips": skips, "harakat_errors": harakat_errors, "incorrect_words": incorrect,
    }


@router.post("/analyze_continuous")
async def analyze_continuous_endpoint(
    surah: int = Form(...),
    from_ayah: int = Form(...),
    to_ayah: int = Form(...),
    audio: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    transcriber: Transcriber = Depends(get_transcriber),
):
    """Huffaz Mode — continuous recitation over a window of Ayahs.
    Scores only up to the confirmed-position pointer (see ai/continuous)."""
    from ..ai.continuous import analyze_continuous
    ref = load_reference()
    if surah not in ref:
        raise HTTPException(400, "Unknown surah")
    if from_ayah not in ref[surah] or to_ayah not in ref[surah] \
            or to_ayah < from_ayah or (to_ayah - from_ayah) > 9:
        raise HTTPException(400, "Invalid ayah window (max 10 ayahs)")
    window = {a: ref[surah][a]["text"] for a in range(from_ayah, to_ayah + 1)}

    raw = await audio.read()
    if not raw:
        raise HTTPException(400, "Empty audio upload")
    suffix = Path(audio.filename or "audio").suffix or ".bin"
    try:
        samples = decode_audio(raw, suffix=suffix)
    except Exception:
        raise HTTPException(400, "Could not decode audio file")
    guard = validate_audio(samples)
    if guard.status != AudioStatus.NORMALIZED_SUCCESS:
        raise HTTPException(400, f"Audio rejected: {guard.status.value}")
    try:
        transcription = transcriber.transcribe(guard.audio)
    except Exception:
        raise HTTPException(503, "Transcription service unavailable")

    result = analyze_continuous(window, transcription)
    if result.status == "no_match":
        return {
            "status": "no_match", "transcription": transcription,
            "detail": "No words in the selected window could be confirmed. "
                      "Check the Surah/ayah range or recite again.",
            "skips": [], "skipped_ayahs": [], "harakat_errors": [],
            "confirmed_position": None, "session_id": None,
        }

    harakat_words = {(e["ayah"], e["word_index"]) for e in result.harakat_errors}
    correct = result.matched_words - len(harakat_words)
    session = RecitationSession(
        user_id=user.id, surah=surah, ayah=from_ayah, transcription=transcription,
        status="ok", mode="continuous", total_words=result.scored_words,
        correct_words=max(correct, 0))
    db.add(session)
    db.flush()
    for s in result.skips:
        db.add(MistakeRecord(
            session_id=session.id, type="skipped", ayah=s.ayah,
            word_index=s.word_index, reference_word=s.word))
    for e in result.harakat_errors:
        db.add(MistakeRecord(
            session_id=session.id, type="harakat", ayah=e["ayah"],
            word_index=e["word_index"], reference_word=e["word"],
            letter=e["letter"], expected_vowel=e["expected_vowel"] or "",
            heard_vowel=e["heard_vowel"] or ""))
    db.commit()

    return {
        "status": "ok", "session_id": session.id,
        "transcription": transcription,
        "confirmed_position": {"ayah": result.confirmed_ayah,
                               "word_index": result.confirmed_word_index},
        "scored_words": result.scored_words, "matched_words": result.matched_words,
        "per_ayah": {str(k): v for k, v in result.per_ayah.items()},
        "skips": [{"ayah": s.ayah, "word_index": s.word_index, "word": s.word}
                  for s in result.skips],
        "skipped_ayahs": result.skipped_ayahs,
        "harakat_errors": result.harakat_errors,
    }


@router.get("/correction_audio")
def correction_audio(surah: int, ayah: int, word: int,
                     word_start: int | None = None, word_end: int | None = None,
                     user: User = Depends(get_current_user)):
    ref = load_reference()
    if surah not in ref or ayah not in ref.get(surah, {}):
        raise HTTPException(400, "Unknown surah/ayah")
    words = ref[surah][ayah]["text"].split()
    if word < 0 or word >= len(words):
        raise HTTPException(400, "Word index out of range (ayah-local, zero-based)")
    start = max(0, word - 1) if word_start is None else word_start
    end = min(len(words) - 1, word + 1) if word_end is None else word_end
    if not 0 <= start <= word <= end < len(words):
        raise HTTPException(400, "Invalid correction phrase range")
    try:
        url, timings = verse_audio(surah, ayah, len(words))
    except Exception:
        raise HTTPException(503, "Phrase audio is unavailable. Please try Listen again.")
    return {
        "surah": surah, "ayah": ayah, "word_index": word,
        "word": words[word],
        "prev_word": words[word - 1] if word > 0 else None,
        "next_word": words[word + 1] if word + 1 < len(words) else None,
        "word_start": start, "word_end": end, "phrase": " ".join(words[start:end + 1]),
        "audio_url": url, "start_ms": timings[start][0], "end_ms": timings[end][1],
        "phrase_audio_available": True,
    }
