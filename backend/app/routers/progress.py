"""History, progress summary, and streak — all computed from real
sessions. No stored counters that can drift, no invented numbers."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import MistakeRecord, RecitationSession, User
from ..security import get_current_user

router = APIRouter(tags=["progress"])


def _session_out(s: RecitationSession) -> dict:
    return {
        "id": s.id, "surah": s.surah, "ayah": s.ayah, "mode": s.mode,
        "transcription": s.transcription, "status": s.status,
        "total_words": s.total_words, "correct_words": s.correct_words,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "mistakes": [{
            "type": m.type, "ayah": m.ayah, "word_index": m.word_index,
            "reference_word": m.reference_word, "letter": m.letter,
            "expected_vowel": m.expected_vowel, "heard_vowel": m.heard_vowel,
        } for m in s.mistakes],
    }


@router.get("/history")
def history(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    sessions = (db.query(RecitationSession)
                .filter(RecitationSession.user_id == user.id)
                .order_by(RecitationSession.created_at.desc()).all())
    return {"sessions": [_session_out(s) for s in sessions], "count": len(sessions)}


@router.get("/history/{session_id}")
def history_one(session_id: int, user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    s = db.get(RecitationSession, session_id)
    if s is None or s.user_id != user.id:
        # 404, not 403: don't leak that another user's session exists (F10).
        raise HTTPException(404, "Session not found")
    return _session_out(s)


@router.get("/progress")
def progress(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    sessions = (db.query(RecitationSession)
                .filter(RecitationSession.user_id == user.id).all())
    total_words = sum(s.total_words for s in sessions)
    correct_words = sum(s.correct_words for s in sessions)
    mistakes = (db.query(MistakeRecord)
                .join(RecitationSession)
                .filter(RecitationSession.user_id == user.id).all())
    by_type = {"skipped": 0, "harakat": 0}
    for m in mistakes:
        by_type[m.type] = by_type.get(m.type, 0) + 1
    return {
        "sessions": len(sessions),
        "ayahs_recited": len({(s.surah, s.ayah) for s in sessions}),
        "total_words": total_words,
        "correct_words": correct_words,
        "accuracy": round(correct_words / total_words, 4) if total_words else None,
        "mistakes_by_type": by_type,
    }


@router.get("/streak")
def streak(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    sessions = (db.query(RecitationSession)
                .filter(RecitationSession.user_id == user.id).all())
    days = sorted({s.created_at.date() for s in sessions if s.created_at},
                  reverse=True)
    if not days:
        return {"current_streak": 0, "total_days": 0, "last_recited": None}
    today = datetime.now(timezone.utc).date()
    current = 0
    # Streak is alive if the latest day is today or yesterday.
    if (today - days[0]).days <= 1:
        expected = days[0]
        for d in days:
            if d == expected:
                current += 1
                expected = d - timedelta(days=1)
            else:
                break
    return {"current_streak": current, "total_days": len(days),
            "last_recited": days[0].isoformat()}
