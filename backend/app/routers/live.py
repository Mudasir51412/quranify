"""Authenticated PCM streaming; microphone reception continues during inference."""
import asyncio
import json
import logging
import time
from dataclasses import replace

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from ..ai.guided import GuidedRecitation
from ..ai.live import LiveRecitation, StableWords
from ..ai.recitation_difficulty import RecitationDifficulty
from ..ai.reference import load_reference
from ..db import get_db
from ..models import MistakeRecord, RecitationSession
from ..security import get_current_user
from .analyze import get_transcriber

router = APIRouter(tags=["live recitation"])
logger = logging.getLogger(__name__)
SAMPLE_RATE = 16000
UPDATE_SAMPLES = 8000  # 500 ms of new audio, never an ayah boundary.
MAX_BUFFER_SAMPLES = SAMPLE_RATE * 20


class StartRecitation(BaseModel):
    token: str = Field(min_length=1, max_length=4096)
    surah: int = Field(ge=1, le=114, strict=True)
    from_ayah: int = Field(ge=1, le=286, strict=True)
    guided: bool = False
    difficulty: RecitationDifficulty = RecitationDifficulty.EXPERT


class AudioBuffer:
    def __init__(self):
        self.pcm = bytearray()
        self.offset = 0
        self.received = 0
        self.voice_end = 0
        self.stopped = False
        self.discard_retry = False
        self.changed = asyncio.Event()

    def append(self, frame: bytes):
        if not frame or len(frame) % 2 or len(frame) > SAMPLE_RATE * 2:
            raise ValueError("Send 16 kHz mono PCM16 frames of at most one second")
        if len(self.pcm) + len(frame) > MAX_BUFFER_SAMPLES * 2:
            raise ValueError("Recognition cannot keep up. Stop and retry on a faster backend.")
        self.pcm.extend(frame)
        self.received += len(frame) // 2
        samples = np.frombuffer(frame, dtype="<i2").astype(np.float32) / 32768
        if float(np.sqrt(np.mean(samples * samples))) > 0.008:
            self.voice_end = self.received
        self.changed.set()

    def retire(self, through_seconds: float):
        # Keep one second of context before the last committed word. Audio that
        # has not been processed is never overwritten, even on a slow CPU.
        if len(self.pcm) <= SAMPLE_RATE * 4 * 2:
            return
        cut = max(0, int((through_seconds - 1.0) * SAMPLE_RATE) - self.offset)
        cut = min(cut, len(self.pcm) // 2)
        del self.pcm[:cut * 2]
        self.offset += cut

    def retire_silence(self, analyzed_through: int):
        """Long pauses must not exhaust the bounded audio buffer."""
        cut = max(0, analyzed_through - SAMPLE_RATE // 2 - self.offset)
        del self.pcm[:cut * 2]
        self.offset += cut


def transcribe_voiced_window(transcriber, audio, offset: float, voice_end: float):
    # Whisper can append plausible words to the end of a decoded phrase.
    # A token starting entirely in trailing silence cannot anchor a skip.
    return [replace(w, start=w.start + offset, end=w.end + offset)
            for w in transcriber.transcribe_words(audio) if w.start + offset < voice_end]


async def run_recognition(socket: WebSocket, buffer: AudioBuffer,
                          tracker: LiveRecitation, transcriber):
    stable = StableWords()
    analyzed = 0
    last_started = 0.0
    last_inference_ms = 0
    final_audio = None
    final_offset = 0.0
    final_voice_end = 0.0
    while True:
        await buffer.changed.wait()
        buffer.changed.clear()
        if not buffer.stopped and buffer.received - analyzed < UPDATE_SAMPLES:
            continue
        if not buffer.stopped:
            await asyncio.sleep(max(0, 0.5 - (time.perf_counter() - last_started)))
        end = buffer.received
        # Silence doesn't cause transcription or missing-word judgments. Allow
        # a short trailing silence to stabilize the last spoken word first.
        has_speech = buffer.voice_end > buffer.offset and not (
            analyzed >= buffer.voice_end + SAMPLE_RATE and end > analyzed)
        if end > analyzed and has_speech:
            offset = buffer.offset / SAMPLE_RATE
            audio = np.frombuffer(bytes(buffer.pcm), dtype="<i2").astype(np.float32) / 32768
            final_audio, final_offset = audio, offset
            final_voice_end = buffer.voice_end / SAMPLE_RATE
            last_started = time.perf_counter()
            absolute = await asyncio.to_thread(
                transcribe_voiced_window, transcriber, audio, offset, final_voice_end)
            last_inference_ms = round((time.perf_counter() - last_started) * 1000)
            committed = stable.update(absolute, final=buffer.stopped and end == buffer.received)
            if not buffer.discard_retry:
                tracker.accept(committed)
            buffer.retire(stable.end)
        elif not has_speech:
            # A natural pause ends the spoken phrase, not the reference ayah.
            # Flush its last hypothesis before retiring silence, just as Stop
            # would; otherwise a final word seen only once could be lost.
            committed = stable.flush()
            if not buffer.discard_retry:
                tracker.accept(committed, final=True)
            buffer.retire(stable.end)
        if not has_speech and end - buffer.voice_end > SAMPLE_RATE * 2:
            buffer.retire_silence(end)
        analyzed = end
        await socket.send_json({
            "type": "feedback", **tracker.snapshot(),
            "inference_ms": last_inference_ms,
            "audio_backlog_ms": round((buffer.received - end) / SAMPLE_RATE * 1000),
            "device": getattr(transcriber, "device", "test"),
        })
        if buffer.discard_retry or (isinstance(tracker, GuidedRecitation) and tracker.segment_done):
            return
        if buffer.stopped and analyzed == buffer.received:
            # Stop may arrive without new samples; finish the existing stable
            # hypothesis, never score the unrecited reference tail.
            committed = stable.flush()
            tracker.accept(committed, final=True)
            if final_audio is not None and tracker.cursor < len(tracker.words):
                # Recheck the last bounded speech window with its full context.
                # It may contain a word which an earlier partial decode omitted;
                # silence retirement must not destroy the chance to recover it.
                absolute = await asyncio.to_thread(
                    transcribe_voiced_window, transcriber, final_audio, final_offset, final_voice_end)
                committed = stable.update(absolute, final=True)
                tracker.accept(committed, final=True)
            return
        if buffer.received > analyzed:
            buffer.changed.set()


async def run_guided_session(socket: WebSocket, tracker: GuidedRecitation, transcriber):
    buffer = None
    worker = None
    receiver = None

    def start_capture():
        nonlocal buffer, worker
        buffer = AudioBuffer()
        worker = asyncio.create_task(run_recognition(socket, buffer, tracker, transcriber))

    async def end_capture(*, pausing: bool = False):
        nonlocal buffer, worker
        if worker is not None:
            buffer.discard_retry = pausing and tracker.retry_index is not None
            buffer.stopped = True
            buffer.changed.set()
            await worker
            buffer = worker = None
        tracker.end_segment()

    async def respond(kind: str):
        await socket.send_json({"type": kind, **tracker.snapshot()})

    start_capture()
    try:
        while True:
            receiver = asyncio.create_task(asyncio.wait_for(socket.receive(), timeout=60))
            if worker is not None and not worker.done():
                await asyncio.wait((receiver, worker), return_when=asyncio.FIRST_COMPLETED)
            if worker is not None and worker.done():
                worker.result()
            message = await receiver
            receiver = None
            if message["type"] == "websocket.disconnect":
                raise WebSocketDisconnect(message.get("code", 1000))
            if message.get("bytes") is not None:
                if buffer is not None and not worker.done():
                    buffer.append(message["bytes"])
                continue
            control = json.loads(message.get("text") or "null")
            if not isinstance(control, dict):
                raise ValueError("Unknown stream command")
            action = control.get("type")
            if action == "ping":
                continue
            if action == "stop":
                await end_capture()
                return
            if action == "pause":
                await end_capture(pausing=True)
                await respond("paused")
                continue
            if action != "resume":
                raise ValueError("Unknown stream command")
            try:
                if worker is not None:
                    raise ValueError("Pause the current audio before resuming.")
                if tracker.completed:
                    raise ValueError("This passage is complete.")
                ayah = control.get("ayah")
                word_index = control.get("word_index")
                replay_ayah = control.get("replay_ayah", False)
                if (ayah is not None and type(ayah) is not int
                        or word_index is not None and type(word_index) is not int
                        or type(replay_ayah) is not bool
                        or (word_index is not None or replay_ayah) and ayah is None
                        or word_index is not None and replay_ayah):
                    raise ValueError("Invalid retry selection.")
                if tracker.blocked and tracker.retry_index is None and word_index is None:
                    raise ValueError("Tap a flagged word to retry.")
                tracker.begin_segment(ayah=ayah, word_index=word_index, replay_ayah=replay_ayah)
            except ValueError as exc:
                await socket.send_json({"type": "control_error", "message": str(exc)})
                continue
            start_capture()
            await respond("resumed")
    finally:
        tasks = [task for task in (worker, receiver) if task is not None]
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


def save_review(db: Session, user, surah: int, from_ayah: int, tracker: LiveRecitation):
    review = tracker.snapshot()
    if not review["confirmed_words"]:
        return {"session_id": None, **review}
    session = RecitationSession(
        user_id=user.id, surah=surah, ayah=from_ayah, mode="continuous",
        status=review["status"],
        transcription=review["transcription"], total_words=review["confirmed_words"],
        correct_words=review["matched_words"])
    db.add(session)
    db.flush()
    for m in review["mistakes"]:
        # Preserve the original kind and correction status without requiring a
        # schema migration on existing installations. History decodes the tag.
        kind = "harakat" if m["reason"] == "harakat" else m["type"]
        if m["corrected"]:
            kind = f"fixed_{kind}"
        detail = (m.get("harakat_errors") or [{}])[0]
        db.add(MistakeRecord(session_id=session.id, type=kind, ayah=m["ayah"],
                             word_index=m["word_index"], reference_word=m["word"],
                             letter=detail.get("letter", ""),
                             expected_vowel=detail.get("expected_vowel", ""),
                             heard_vowel=detail.get("heard_vowel", "")))
    user.last_surah = surah
    user.last_ayah = review["current_ayah"]
    db.commit()
    return {"session_id": session.id, **review}


@router.websocket("/recite/live")
async def recite_live(socket: WebSocket, db: Session = Depends(get_db),
                      transcriber=Depends(get_transcriber)):
    await socket.accept()
    tasks = []
    try:
        start = StartRecitation.model_validate(
            await asyncio.wait_for(socket.receive_json(), timeout=10))
        user = get_current_user(
            HTTPAuthorizationCredentials(scheme="Bearer", credentials=start.token), db)
        corpus = load_reference()
        reference = corpus.get(start.surah, {})
        if start.from_ayah not in reference:
            raise ValueError("Unknown starting ayah")
        if not hasattr(transcriber, "transcribe_words"):
            raise ValueError("This backend does not support live speech recognition")
        window = {a: row["text"] for a, row in reference.items() if a >= start.from_ayah}
        if start.guided:
            vocabulary = None if start.difficulty == RecitationDifficulty.EXPERT else {
                word for verses in corpus.values() for row in verses.values() for word in row["words"]
            }
            tracker = GuidedRecitation(window, difficulty=start.difficulty, vocabulary=vocabulary)
        else:
            tracker = LiveRecitation(window)
        # The client keeps its microphone off until the model has loaded.
        device = await asyncio.to_thread(transcriber.prepare_stream)
        await socket.send_json({"type": "ready", "device": device, "sample_rate": SAMPLE_RATE,
                                "engine": getattr(transcriber, "engine", "test"),
                                "guided": start.guided,
                                "difficulty": start.difficulty})
        if isinstance(tracker, GuidedRecitation):
            await run_guided_session(socket, tracker, transcriber)
            review = save_review(db, user, start.surah, start.from_ayah, tracker)
            await socket.send_json({"type": "finished", **review})
            await socket.close()
            return
        buffer = AudioBuffer()

        async def receive_audio():
            while True:
                message = await asyncio.wait_for(socket.receive(), timeout=60)
                if message["type"] == "websocket.disconnect":
                    raise WebSocketDisconnect(message.get("code", 1000))
                if message.get("bytes") is not None:
                    buffer.append(message["bytes"])
                elif message.get("text"):
                    control = json.loads(message["text"])
                    if not isinstance(control, dict) or control.get("type") != "stop":
                        raise ValueError("Unknown stream command")
                    buffer.stopped = True
                    buffer.changed.set()
                    return

        receiver = asyncio.create_task(receive_audio())
        recognizer = asyncio.create_task(run_recognition(socket, buffer, tracker, transcriber))
        tasks = [receiver, recognizer]
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()  # Surface disconnects and worker failures immediately.
        await recognizer
        review = save_review(db, user, start.surah, start.from_ayah, tracker)
        await socket.send_json({"type": "finished", **review})
        await socket.close()
    except WebSocketDisconnect:
        pass
    except (ValueError, ValidationError, HTTPException, asyncio.TimeoutError) as exc:
        detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
        await socket.send_json({"type": "error", "message": detail or "Recitation connection timed out"})
        await socket.close(code=1008)
    except Exception:
        logger.exception("Live recitation failed")
        await socket.send_json({"type": "error", "message": "Speech service unavailable. Check the backend and try again."})
        await socket.close(code=1011)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
