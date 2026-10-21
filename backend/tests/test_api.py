"""API tests — executes the report's functional spec (F01-F12, §5.2) that
was 'Not run' in their testing chapter, plus auth and privacy rules."""
import io
import wave

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.routers.analyze import get_transcriber
from app.services.transcriber import FakeTranscriber

fake = FakeTranscriber("")

# StaticPool: one shared connection, so the in-memory DB is the same
# database for every request thread TestClient spawns.
engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                       poolclass=StaticPool)
TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base.metadata.create_all(bind=engine)


def _override_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_db
app.dependency_overrides[get_transcriber] = lambda: fake

client = TestClient(app)
_counter = [0]


def make_wav(silent: bool = False, seconds: float = 1.0) -> bytes:
    sr = 16000
    if silent:
        samples = np.zeros(int(sr * seconds), dtype=np.int16)
    else:
        rng = np.random.default_rng(3)
        samples = (rng.standard_normal(int(sr * seconds)) * 8000).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(samples.tobytes())
    return buf.getvalue()


def register() -> dict:
    _counter[0] += 1
    email = f"user{_counter[0]}@test.local"
    r = client.post("/auth/register", json={
        "email": email, "password": "secret123", "name": "Tester", "mode": "normal"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['token']}", "email": email}


def ayah_text(surah: int, ayah: int) -> str:
    r = client.get(f"/quran/surah/{surah}")
    return next(a["text"] for a in r.json()["ayahs"] if a["ayah"] == ayah)


def analyze(headers, surah, ayah, wav=None):
    return client.post(
        "/analyze", headers=headers,
        data={"surah": surah, "ayah": ayah},
        files={"audio": ("rec.wav", wav if wav is not None else make_wav(),
                         "audio/wav")})


# --- Quran browsing (F01, F02) ---

def test_f01_load_surah_1():
    r = client.get("/quran/surah/1")
    assert r.status_code == 200
    body = r.json()
    assert len(body["ayahs"]) == 7
    assert body["ayahs"][0]["ayah"] == 1

def test_f02_available_surahs():
    r = client.get("/quran/surahs")
    assert r.status_code == 200 and r.json()["count"] == 114
    r2 = client.get("/available_surahs")
    assert 112 in r2.json()["available_surahs"]

def test_surah_not_found():
    assert client.get("/quran/surah/999").status_code == 404


# --- Auth (FR-14, FR-15, FR-19, SEC-3) ---

def test_register_login_me_logout():
    _counter[0] += 1
    email = f"auth{_counter[0]}@test.local"
    r = client.post("/auth/register", json={"email": email, "password": "secret123"})
    assert r.status_code == 201
    dup = client.post("/auth/register", json={"email": email, "password": "secret123"})
    assert dup.status_code == 400
    bad = client.post("/auth/login", json={"email": email, "password": "wrong-pass"})
    assert bad.status_code == 401
    ok = client.post("/auth/login", json={"email": email, "password": "secret123"})
    assert ok.status_code == 200
    headers = {"Authorization": f"Bearer {ok.json()['token']}"}
    me = client.get("/auth/me", headers=headers)
    assert me.status_code == 200 and me.json()["email"] == email
    assert client.post("/auth/logout", headers=headers).status_code == 200

def test_me_requires_auth():
    assert client.get("/auth/me").status_code == 401

def test_short_password_rejected():
    r = client.post("/auth/register", json={"email": "x@y.z", "password": "123"})
    assert r.status_code == 400


# --- Analyze flow (F03, F04, F06) ---

def test_f03_analyze_correct_recitation():
    headers = register()
    fake.text = ayah_text(112, 1)
    r = analyze(headers, 112, 1)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok" and body["skips"] == [] and body["harakat_errors"] == []
    hist = client.get("/history", headers=headers)
    assert hist.json()["count"] == 1

def test_f04_analyze_detects_omission():
    headers = register()
    words = ayah_text(112, 1).split()
    fake.text = " ".join(w for i, w in enumerate(words) if i != 2)
    r = analyze(headers, 112, 1)
    assert r.status_code == 200
    assert [s["index"] for s in r.json()["skips"]] == [2]
    detail = client.get(f"/history/{r.json()['session_id']}", headers=headers)
    skipped = [m for m in detail.json()["mistakes"] if m["type"] == "skipped"]
    assert len(skipped) == 1 and skipped[0]["word_index"] == 2

def test_analyze_detects_harakat_error():
    headers = register()
    fake.text = ayah_text(1, 1).replace("بِسْمِ", "بَسْمِ", 1)
    r = analyze(headers, 1, 1)
    assert r.status_code == 200
    errs = r.json()["harakat_errors"]
    assert len(errs) >= 1
    assert any(e["expected_vowel"] == "kasra" and e["heard_vowel"] == "fatha" for e in errs)

def test_f06_silent_audio_rejected_and_not_saved():
    headers = register()
    fake.text = ayah_text(112, 1)
    before = client.get("/history", headers=headers).json()["count"]
    r = analyze(headers, 112, 1, wav=make_wav(silent=True))
    assert r.status_code == 400
    after = client.get("/history", headers=headers).json()["count"]
    assert after == before

def test_analyze_requires_auth():
    fake.text = "x"
    r = client.post("/analyze", data={"surah": 112, "ayah": 1},
                    files={"audio": ("a.wav", make_wav(), "audio/wav")})
    assert r.status_code == 401

def test_analyze_unknown_ayah():
    headers = register()
    r = analyze(headers, 112, 99)
    assert r.status_code == 400


# --- Correction audio contract (F05) ---

def test_correction_audio_word_and_context():
    headers = register()
    r = client.get("/correction_audio", headers=headers,
                   params={"surah": 112, "ayah": 1, "word": 0})
    assert r.status_code == 200
    body = r.json()
    assert body["word_index"] == 0 and body["prev_word"] is None
    assert body["next_word"] is not None
    bad = client.get("/correction_audio", headers=headers,
                     params={"surah": 112, "ayah": 1, "word": 99})
    assert bad.status_code == 400


# --- Privacy (F10) ---

def test_f10_other_users_session_hidden():
    owner = register()
    fake.text = ayah_text(112, 2)
    sid = analyze(owner, 112, 2).json()["session_id"]
    intruder = register()
    r = client.get(f"/history/{sid}", headers=intruder)
    assert r.status_code == 404


# --- Progress, streak, daily ---

def test_progress_and_streak_after_sessions():
    headers = register()
    fake.text = ayah_text(112, 1)
    analyze(headers, 112, 1)
    words = ayah_text(112, 2).split()
    fake.text = " ".join(words[:-1])  # one skip
    analyze(headers, 112, 2)
    p = client.get("/progress", headers=headers).json()
    assert p["sessions"] == 2 and p["ayahs_recited"] == 2
    assert p["mistakes_by_type"]["skipped"] == 1
    assert 0 < p["accuracy"] < 1
    s = client.get("/streak", headers=headers).json()
    assert s["current_streak"] == 1 and s["total_days"] == 1

def test_daily_content():
    r = client.get("/daily")
    assert r.status_code == 200
    body = r.json()
    assert body["ayah"]["text"] and body["hadith"]["source"]

def test_health():
    assert client.get("/health").json()["status"] == "ok"


# --- Complete version: profile, reading position, home ---

def test_profile_patch_and_reading_position():
    headers = register()
    r = client.patch("/auth/me", headers=headers,
                     json={"mode": "hafiz", "notifications_enabled": False})
    assert r.status_code == 200
    assert r.json()["mode"] == "hafiz" and r.json()["notifications_enabled"] is False
    bad = client.patch("/auth/me", headers=headers, json={"mode": "weird"})
    assert bad.status_code == 400
    pos = client.put("/auth/reading-position", headers=headers,
                     json={"surah": 112, "ayah": 3})
    assert pos.status_code == 200
    me = client.get("/auth/me", headers=headers).json()
    assert me["last_surah"] == 112 and me["last_ayah"] == 3
    bad_pos = client.put("/auth/reading-position", headers=headers,
                         json={"surah": 112, "ayah": 99})
    assert bad_pos.status_code == 400
    home = client.get("/home", headers=headers)
    assert home.status_code == 200
    assert home.json()["continue_reading"]["ayah"] == 3
    assert home.json()["daily"]["ayah"]["text"]


# --- Complete version: gamification ---

def test_gamification_points_and_badges():
    headers = register()
    fake.text = ayah_text(112, 1)  # perfect 4-word ayah
    analyze(headers, 112, 1)
    g = client.get("/gamification", headers=headers).json()
    # points = 4 correct words + 10 session + 15 perfect bonus
    assert g["points"] == 29 and g["level"] == 1
    badges = {b["id"]: b for b in g["badges"]}
    assert badges["first_recitation"]["earned"] is True
    assert badges["perfect_ayah"]["earned"] is True
    assert badges["hundred_words"]["earned"] is False

def test_surah_complete_badge():
    headers = register()
    for a in (1, 2, 3, 4):
        fake.text = ayah_text(112, a)
        analyze(headers, 112, a)
    g = client.get("/gamification", headers=headers).json()
    assert 112 in g["completed_surahs"]
    badges = {b["id"]: b for b in g["badges"]}
    assert badges["surah_complete"]["earned"] is True


# --- Complete version: Huffaz continuous mode ---

def _analyze_continuous(headers, surah, from_ayah, to_ayah):
    return client.post(
        "/analyze_continuous", headers=headers,
        data={"surah": surah, "from_ayah": from_ayah, "to_ayah": to_ayah},
        files={"audio": ("rec.wav", make_wav(), "audio/wav")})

def test_continuous_skipped_ayah():
    headers = register()
    fake.text = ayah_text(112, 1) + " " + ayah_text(112, 3)
    r = _analyze_continuous(headers, 112, 1, 3)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert body["skipped_ayahs"] == [2]
    assert body["confirmed_position"]["ayah"] == 3
    assert all(s["ayah"] == 2 for s in body["skips"])

def test_continuous_tail_not_scored():
    headers = register()
    fake.text = ayah_text(112, 1)
    r = _analyze_continuous(headers, 112, 1, 4)
    body = r.json()
    assert body["status"] == "ok" and body["skips"] == []
    assert body["scored_words"] == 4
    assert body["confirmed_position"] == {"ayah": 1, "word_index": 3}

def test_continuous_no_match():
    headers = register()
    fake.text = "ذهب خالد الى السوق"
    before = client.get("/history", headers=headers).json()["count"]
    r = _analyze_continuous(headers, 112, 1, 3)
    assert r.json()["status"] == "no_match" and r.json()["session_id"] is None
    assert client.get("/history", headers=headers).json()["count"] == before

def test_continuous_window_validation():
    headers = register()
    r = _analyze_continuous(headers, 112, 3, 1)
    assert r.status_code == 400


# --- Complete version: offline sync (FR-18) ---

def test_sync_idempotent_and_validated():
    headers = register()
    item = {"client_uuid": "uuid-1", "surah": 112, "ayah": 1,
            "transcription": ayah_text(112, 1)}
    r = client.post("/sync/sessions", headers=headers, json={"items": [item]})
    assert r.json()["results"][0]["status"] == "synced"
    count = client.get("/history", headers=headers).json()["count"]
    r2 = client.post("/sync/sessions", headers=headers, json={"items": [item]})
    assert r2.json()["results"][0]["status"] == "already_synced"
    assert client.get("/history", headers=headers).json()["count"] == count
    bad = {"client_uuid": "uuid-2", "surah": 112, "ayah": 99, "transcription": "x"}
    r3 = client.post("/sync/sessions", headers=headers, json={"items": [bad]})
    assert r3.json()["results"][0]["status"] == "rejected"
