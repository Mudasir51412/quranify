"""Complete-version routes: gamification, home aggregate, offline sync."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..ai.pipeline import analyze_recitation
from ..ai.reference import load_reference
from ..db import get_db
from ..models import MistakeRecord, RecitationSession, User
from ..security import get_current_user
from ..services.gamification import compute_gamification
from .daily import daily as daily_content
from .progress import streak as streak_for

router = APIRouter(tags=["complete"])


def _sessions(db: Session, user: User) -> list[RecitationSession]:
    return (db.query(RecitationSession)
            .filter(RecitationSession.user_id == user.id).all())


@router.get("/gamification")
def gamification(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return compute_gamification(_sessions(db, user))


@router.get("/home")
def home(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    sessions = _sessions(db, user)
    total_words = sum(s.total_words for s in sessions)
    correct_words = sum(s.correct_words for s in sessions)
    continue_reading = None
    if user.last_surah is not None and user.last_ayah is not None:
        ref = load_reference()
        if user.last_surah in ref and user.last_ayah in ref.get(user.last_surah, {}):
            continue_reading = {
                "surah": user.last_surah, "ayah": user.last_ayah,
                "text": ref[user.last_surah][user.last_ayah]["text"],
            }
    return {
        "user": {"id": user.id, "name": user.name, "mode": user.mode},
        "daily": daily_content(),
        "streak": streak_for(user, db),
        "continue_reading": continue_reading,
        "summary": {
            "sessions": len(sessions),
            "accuracy": round(correct_words / total_words, 4) if total_words else None,
        },
        "gamification": compute_gamification(sessions),
    }


class SyncItem(BaseModel):
    client_uuid: str
    surah: int
    ayah: int
    transcription: str
    created_at: datetime | None = None


class SyncIn(BaseModel):
    items: list[SyncItem]


@router.post("/sync/sessions")
def sync_sessions(body: SyncIn, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    """FR-18: upload sessions recorded offline (e.g. transcribed on-device).
    Idempotent per (user, client_uuid) — a retry never duplicates a
    session. Sync never overwrites: items are insert-only, and a UUID
    conflict returns the existing session id."""
    ref = load_reference()
    results = []
    for item in body.items:
        existing = (db.query(RecitationSession)
                    .filter(RecitationSession.user_id == user.id,
                            RecitationSession.client_uuid == item.client_uuid)
                    .first())
        if existing:
            results.append({"client_uuid": item.client_uuid,
                            "status": "already_synced", "session_id": existing.id})
            continue
        if item.surah not in ref or item.ayah not in ref.get(item.surah, {}):
            results.append({"client_uuid": item.client_uuid,
                            "status": "rejected", "reason": "UNKNOWN_AYAH"})
            continue
        reference_text = ref[item.surah][item.ayah]["text"]
        analysis = analyze_recitation(reference_text, item.transcription)
        if analysis.status == "rejected":
            results.append({"client_uuid": item.client_uuid,
                            "status": "rejected", "reason": analysis.reason})
            continue
        skipped_idx = {s.index for s in analysis.skips}
        correct = analysis.total_words - len(skipped_idx) - len(
            {e.word_index for e in analysis.harakat_errors})
        session = RecitationSession(
            user_id=user.id, surah=item.surah, ayah=item.ayah,
            transcription=item.transcription, status=analysis.status,
            mode="sync", client_uuid=item.client_uuid,
            total_words=analysis.total_words, correct_words=max(correct, 0))
        if item.created_at is not None:
            session.created_at = item.created_at
        db.add(session)
        db.flush()
        words = reference_text.split()
        for s in analysis.skips:
            db.add(MistakeRecord(
                session_id=session.id, type="skipped", ayah=item.ayah,
                word_index=s.index,
                reference_word=words[s.index] if s.index < len(words) else s.word))
        for e in analysis.harakat_errors:
            wi = e.word_index or 0
            db.add(MistakeRecord(
                session_id=session.id, type="harakat", ayah=item.ayah,
                word_index=wi,
                reference_word=words[wi] if wi < len(words) else "",
                letter=e.letter, expected_vowel=e.expected_vowel or "",
                heard_vowel=e.heard_vowel or ""))
        db.commit()
        results.append({"client_uuid": item.client_uuid,
                        "status": "synced", "session_id": session.id})
    return {"results": results}
