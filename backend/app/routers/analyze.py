"""
POST /analyze — the core endpoint (report Table 4.6).

Flow: auth -> validate surah/ayah -> decode audio -> guardrails
(reject BEFORE scoring, no session saved for invalid audio) ->
transcribe -> AI pipeline -> persist session + mistakes -> respond.

GET /correction_audio — word-level contract (ayah-local index).
Word-level MP3 assets (Buraaq quran-md-words) are a planned single
download; until that asset lands, the endpoint returns the word, its
context, and the Ayah-level reference audio URL pattern instead of
pretending a word file exists.
"""
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..ai.audio_guardrails import AudioStatus, validate_audio
from ..ai.pipeline import analyze_recitation
from ..ai.reference import load_reference
from ..db import get_db
from ..models import MistakeRecord, RecitationSession, User
from ..security import get_current_user
from ..services.transcriber import Transcriber, decode_audio

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
        _transcriber = WhisperTranscriber(settings.model_id)
    return _transcriber


@router.post("/analyze")
async def analyze(
    surah: int = Form(...),
    ayah: int = Form(...),
    audio: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    transcriber: Transcriber = Depends(get_transcriber),
):
    ref = load_reference()
    if surah not in ref or ayah not in ref.get(surah, {}):
        raise HTTPException(400, "Unknown surah/ayah")
    reference_text = ref[surah][ayah]["text"]
    ref_words = reference_text.split()

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
        transcription = transcriber.transcribe(guard.audio)
    except Exception:
        raise HTTPException(503, "Transcription service unavailable")

    result = analyze_recitation(reference_text, transcription)
    if result.status == "rejected":
        raise HTTPException(400, f"Analysis rejected: {result.reason}")

    skipped_idx = {s.index for s in result.skips}
    correct = result.total_words - len(skipped_idx) - len(
        {e.word_index for e in result.harakat_errors})
    session = RecitationSession(
        user_id=user.id, surah=surah, ayah=ayah, transcription=transcription,
        status=result.status, mode="single", total_words=result.total_words,
        correct_words=max(correct, 0))
    db.add(session)
    db.flush()
    for s in result.skips:
        db.add(MistakeRecord(
            session_id=session.id, type="skipped", ayah=ayah, word_index=s.index,
            reference_word=ref_words[s.index] if s.index < len(ref_words) else s.word))
    for e in result.harakat_errors:
        wi = e.word_index or 0
        db.add(MistakeRecord(
            session_id=session.id, type="harakat", ayah=ayah, word_index=wi,
            reference_word=ref_words[wi] if wi < len(ref_words) else "",
            letter=e.letter, expected_vowel=e.expected_vowel or "",
            heard_vowel=e.heard_vowel or ""))
    db.commit()

    return {
        "session_id": session.id,
        "status": result.status,
        "reason": result.reason,
        "transcription": transcription,
        "reference": reference_text,
        "total_words": result.total_words,
        "skips": [{"index": s.index, "word": ref_words[s.index]}
                  for s in result.skips if s.index < len(ref_words)],
        "harakat_errors": [{
            "word_index": e.word_index, "letter": e.letter,
            "expected_vowel": e.expected_vowel, "heard_vowel": e.heard_vowel,
            "word": ref_words[e.word_index] if e.word_index is not None
                    and e.word_index < len(ref_words) else "",
        } for e in result.harakat_errors],
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
                     user: User = Depends(get_current_user)):
    ref = load_reference()
    if surah not in ref or ayah not in ref.get(surah, {}):
        raise HTTPException(400, "Unknown surah/ayah")
    words = ref[surah][ayah]["text"].split()
    if word < 0 or word >= len(words):
        raise HTTPException(400, "Word index out of range (ayah-local, zero-based)")
    return {
        "surah": surah, "ayah": ayah, "word_index": word,
        "word": words[word],
        "prev_word": words[word - 1] if word > 0 else None,
        "next_word": words[word + 1] if word + 1 < len(words) else None,
        "word_audio_available": False,
        "word_audio_note": "Word-level MP3s (Buraaq quran-md-words) not yet downloaded; "
                           "use ayah_audio_url for contextual playback meanwhile.",
        "ayah_audio_url": f"https://everyayah.com/data/Alafasy_128kbps/{surah:03d}{ayah:03d}.mp3",
    }
