"""Live tracking: no false tail skips, stability, corrections, and streaming auth."""
import uuid

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai.live import LiveRecitation, StableWords
from app.db import Base, get_db
from app.main import app
from app.routers.analyze import get_transcriber
from app.routers.live import AudioBuffer
from app.services.transcriber import SpokenWord


def tracker():
    return LiveRecitation({1: "قُلْ هُوَ ٱللَّهُ أَحَدٌ", 2: "ٱللَّهُ ٱلصَّمَدُ"})


def test_pause_and_unread_tail_are_not_mistakes():
    live = tracker()
    live.accept(["قُلْ"])
    live.accept([])
    live.accept([], final=True)
    assert live.snapshot()["scored_words"] == 1
    assert live.snapshot()["mistakes"] == []


def test_skip_is_revealed_only_after_a_later_anchor_then_correction_hides_it():
    live = tracker()
    live.accept(["قُلْ"])
    assert not live.mistakes
    live.accept(["اللَّهُ"])
    assert live.states[1] == "skipped"
    assert live.cursor == 3
    live.accept(["هُوَ"])
    assert live.states[1] == "matched"
    assert live.mistakes[1]["corrected"] is True
    assert live.cursor == 3  # Revisiting doesn't rewind the forward position.
    live.accept(["أَحَدٌ", "اللَّهُ", "الصَّمَدُ"])
    assert live.snapshot()["completed"] is True


def test_wrong_word_needs_following_anchor_and_can_be_corrected():
    live = tracker()
    live.accept(["قُلْ", "كتاب"])
    assert not live.mistakes
    live.accept(["اللَّهُ"])
    assert live.states[1] == "incorrect"
    live.accept(["هُوَ"])
    assert live.mistakes[1]["corrected"]


def test_wrong_vowel_is_not_cleared_without_vowel_evidence():
    live = tracker()
    live.accept(["قَلْ"])
    assert live.states[0] == "incorrect"
    live.accept(["قل"])
    assert live.states[0] == "incorrect"
    live.accept(["قُلْ"])
    assert live.states[0] == "matched"
    assert live.mistakes[0]["corrected"]


def test_correction_after_crossing_an_ayah_and_correct_repetitions():
    live = tracker()
    live.accept(["قُلْ", "اللَّهُ", "أَحَدٌ", "اللَّهُ"])
    assert live.cursor == 5
    live.accept(["اللَّهُ"])
    assert live.cursor == 5
    live.accept(["هُوَ"])
    assert live.mistakes[1]["corrected"]


def test_extra_speech_does_not_stall_following_words():
    live = tracker()
    live.accept(["قُلْ", "كتاب", "هُوَ", "اللَّهُ"])
    assert live.cursor == 3
    assert not live.mistakes


def test_split_arabic_tokens_do_not_stall_the_following_ayah():
    live = LiveRecitation({3: "لَمْ يَلِدْ وَلَمْ يُولَدْ", 4: "وَلَمْ يَكُن لَّهُۥ كُفُوًا أَحَدٌ"})
    live.accept(["لَمْ", "يَلِدْ", "وَلَا", "مْ", "يُولَدْ", "وَلَمْ", "يَكُن", "لَّهُ", "كُفُوًا", "أَحَدٌ"])
    assert live.snapshot()["completed"] is True
    assert live.snapshot()["uncertain_words"] >= 1
    assert live.mistakes == {}


def test_exact_split_tokens_are_joined_without_a_false_skip():
    live = LiveRecitation({1: "الحمد لله"})
    live.accept(["ال", "حمد", "لله"])
    assert live.snapshot()["completed"] is True
    assert not live.mistakes


def test_long_jump_requires_two_consecutive_anchors():
    live = tracker()
    live.accept(["الصَّمَدُ"])
    assert live.cursor == 0
    assert not live.mistakes


def test_hypotheses_must_agree_and_old_audio_is_not_counted_twice():
    stable = StableWords()
    first = [SpokenWord("قُلْ", 0, 0.3)]
    assert stable.update(first) == []
    assert stable.update([SpokenWord("قَلْ", 0, 0.3)]) == []
    assert stable.update(first) == []
    assert stable.update(first) == first
    assert stable.update(first) == []
    tail = SpokenWord("هُوَ", 0.4, 0.7)
    assert stable.update(first + [tail]) == []
    assert stable.update(first + [tail], final=True) == [tail]


def test_changed_end_timestamp_does_not_repeat_a_committed_word():
    stable = StableWords()
    first = [SpokenWord("قُلْ", 0, 0.3)]
    stable.update(first)
    stable.update(first)
    grown = [SpokenWord("قُلْ", 0, 0.45), SpokenWord("هُوَ", 0.5, 0.8)]
    assert stable.update(grown) == []
    assert stable.update(grown) == [grown[1]]


def test_window_retiming_does_not_drop_a_new_overlapping_word():
    stable = StableWords()
    first = [SpokenWord("قُلْ", 0.0, 0.5)]
    stable.update(first)
    stable.update(first)
    # A rolling decode moves the next word's start earlier than the previous
    # decode's end. Its identity and end still establish a new occurrence.
    next_word = SpokenWord("هُوَ", 0.3, 0.8)
    assert stable.update(first + [next_word]) == []
    assert stable.update(first + [next_word]) == [next_word]


def test_repeated_word_at_a_new_audio_position_is_not_deduplicated():
    stable = StableWords()
    first = [SpokenWord("اللَّهُ", 0.0, 0.5)]
    stable.update(first)
    stable.update(first)
    repeated = SpokenWord("اللَّهُ", 0.6, 1.1)
    stable.update(first + [repeated])
    assert stable.update(first + [repeated]) == [repeated]


def test_retiring_a_long_pause_preserves_newly_received_audio():
    buffer = AudioBuffer()
    buffer.pcm = bytearray(16000 * 10 * 2)
    buffer.received = 16000 * 10
    buffer.retire_silence(16000 * 8)
    assert buffer.offset == 16000 * 7.5
    assert len(buffer.pcm) == 16000 * 2.5 * 2


def test_buffer_keeps_unprocessed_audio_and_rejects_overrun():
    buffer = AudioBuffer()
    frame = np.ones(8000, dtype="<i2").tobytes()
    for _ in range(20):
        buffer.append(frame)
    buffer.retire(5)
    assert buffer.offset == 64000
    assert len(buffer.pcm) == (160000 - 64000) * 2
    with pytest.raises(ValueError):
        buffer.append(b"odd")
    for _ in range(28):
        buffer.append(frame)
    with pytest.raises(ValueError, match="cannot keep up"):
        buffer.append(frame)


class StreamingFake:
    device = "cpu"

    def __init__(self):
        self.calls = 0

    def prepare_stream(self):
        return self.device

    def transcribe_words(self, audio):
        self.calls += 1
        # Skip hu, then say it later as a correction. Timing is absolute in
        # this short fixture; real recognition returns window-relative times.
        words = [SpokenWord("قُلْ", 0.05, 0.2), SpokenWord("اللَّهُ", 0.25, 0.45)]
        if len(audio) >= 16000:
            words.append(SpokenWord("هُوَ", 0.55, 0.85))
        return words


@pytest.fixture
def streaming_client():
    previous = dict(app.dependency_overrides)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    factory = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)

    def db_override():
        with factory() as db:
            yield db

    fake = StreamingFake()
    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[get_transcriber] = lambda: fake
    with TestClient(app) as client:
        yield client, fake
    app.dependency_overrides.clear()
    app.dependency_overrides.update(previous)
    engine.dispose()


def register(client):
    response = client.post("/auth/register", json={
        "email": f"live-{uuid.uuid4()}@test.local", "password": "secret123"})
    assert response.status_code == 201
    return response.json()["token"]


def test_live_feedback_arrives_before_stop_and_history_retains_correction(streaming_client):
    client, fake = streaming_client
    token = register(client)
    frame = (np.sin(np.arange(8000) * 0.1) * 6000).astype("<i2").tobytes()
    with client.websocket_connect("/recite/live") as ws:
        ws.send_json({"token": token, "surah": 112, "from_ayah": 1})
        assert ws.receive_json()["type"] == "ready"
        ws.send_bytes(frame)
        assert ws.receive_json()["scored_words"] == 0
        ws.send_bytes(frame)
        live = ws.receive_json()
        assert live["type"] == "feedback"
        assert live["mistakes"][0]["type"] == "skipped"
        ws.send_bytes(frame)
        corrected = ws.receive_json()
        assert corrected["mistakes"][0]["corrected"] is True
        ws.send_json({"type": "stop"})
        while True:
            review = ws.receive_json()
            if review["type"] == "finished":
                break
        assert review["session_id"] is not None
        assert review["scored_words"] == 3  # No false skip of ahad or later ayahs.
    history = client.get("/history", headers={"Authorization": f"Bearer {token}"}).json()
    assert len(history["sessions"]) == 1
    mistake = history["sessions"][0]["mistakes"][0]
    assert mistake["type"] == "skipped"
    assert mistake["corrected"] is True
    assert fake.calls >= 3


def test_live_rejects_bad_auth_before_loading_model(streaming_client):
    client, fake = streaming_client
    with client.websocket_connect("/recite/live") as ws:
        ws.send_json({"token": "invalid", "surah": 112, "from_ayah": 1})
        assert ws.receive_json()["type"] == "error"
    assert fake.calls == 0


def test_silence_does_not_invoke_model_or_save_an_empty_session(streaming_client):
    client, fake = streaming_client
    token = register(client)
    with client.websocket_connect("/recite/live") as ws:
        ws.send_json({"token": token, "surah": 112, "from_ayah": 1})
        ws.receive_json()
        ws.send_bytes(bytes(16000))
        assert ws.receive_json()["mistakes"] == []
        ws.send_json({"type": "stop"})
        while (review := ws.receive_json())["type"] != "finished":
            pass
        assert review["session_id"] is None
    assert fake.calls == 0
