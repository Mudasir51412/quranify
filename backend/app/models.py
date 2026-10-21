"""Database models: User -> RecitationSession -> MistakeRecord."""
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(120), default="")
    mode: Mapped[str] = mapped_column(String(16), default="normal")  # normal | hafiz
    notifications_enabled: Mapped[bool] = mapped_column(default=True)
    last_surah: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_ayah: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    sessions: Mapped[list["RecitationSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan")


class RecitationSession(Base):
    __tablename__ = "recitation_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    surah: Mapped[int] = mapped_column(Integer)
    ayah: Mapped[int] = mapped_column(Integer)
    transcription: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="ok")  # ok | uncertain
    mode: Mapped[str] = mapped_column(String(16), default="single")  # single | continuous | sync
    client_uuid: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    total_words: Mapped[int] = mapped_column(Integer, default=0)
    correct_words: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)

    user: Mapped[User] = relationship(back_populates="sessions")
    mistakes: Mapped[list["MistakeRecord"]] = relationship(
        back_populates="session", cascade="all, delete-orphan")


class MistakeRecord(Base):
    __tablename__ = "mistake_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("recitation_sessions.id"), index=True)
    type: Mapped[str] = mapped_column(String(16))  # skipped | harakat
    ayah: Mapped[int] = mapped_column(Integer, default=0)  # ayah the mistake belongs to
    word_index: Mapped[int] = mapped_column(Integer)  # ayah-local, zero-based
    reference_word: Mapped[str] = mapped_column(String(120), default="")
    letter: Mapped[str] = mapped_column(String(8), default="")
    expected_vowel: Mapped[str] = mapped_column(String(16), default="")
    heard_vowel: Mapped[str] = mapped_column(String(16), default="")

    session: Mapped[RecitationSession] = relationship(back_populates="mistakes")
