"""Authenticated PCM streaming; microphone reception continues during inference."""
import asyncio
import json
import logging
import time

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from ..ai.live import LiveRecitation, StableWords
from ..ai.reference import load_reference
from ..db import get_db
from ..models import MistakeRecord, RecitationSession
from ..security import get_current_user
from ..services.transcriber import SpokenWord
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


class AudioBuffer:
    def __init__(self):
        self.pcm = bytearray()
        self.offset = 0
        self.received = 0
        self.voice_end = 0
        self.stopped = False
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


async def run_recognition(socket: WebSocket, buffer: AudioBuffer,
                          tracker: LiveRecitation, transcriber):
    stable = StableWords()
    analyzed = 0
    last_started = 0.0
    last_inference_ms = 0
    final_audio = None
    final_offset = 0.0
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
            last_started = time.perf_counter()
            words = await asyncio.to_thread(transcriber.transcribe_words, audio)
            last_inference_ms = round((time.perf_counter() - last_started) * 1000)
            absolute = [SpokenWord(w.text, w.start + offset, w.end + offset) for w in words]
            committed = stable.update(absolute, final=buffer.stopped and end == buffer.received)
            tracker.accept([w.text for w in committed])
            buffer.retire(stable.end)
        elif not has_speech and stable.previous:
            # A natural pause ends the spoken phrase, not the reference ayah.
            # Flush its last hypothesis before retiring silence, just as Stop
            # would; otherwise a final word seen only once could be lost.
            committed = stable.update(stable.previous, final=True)
            tracker.accept([w.text for w in committed])
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
        if buffer.stopped and analyzed == buffer.received:
            # Stop may arrive without new samples; finish the existing stable
            # hypothesis, never score the unrecited reference tail.
            committed = stable.update(stable.previous, final=True)
            tracker.accept([w.text for w in committed], final=True)
            if final_audio is not None and tracker.cursor < len(tracker.words):
                # Recheck the last bounded speech window with its full context.
                # It may contain a word which an earlier partial decode omitted;
                # silence retirement must not destroy the chance to recover it.
                words = await asyncio.to_thread(transcriber.transcribe_words, final_audio)
                absolute = [SpokenWord(w.text, w.start + final_offset, w.end + final_offset)
                            for w in words]
                committed = stable.update(absolute, final=True)
                tracker.accept([w.text for w in committed], final=True)
            return
        if buffer.received > analyzed:
            buffer.changed.set()


def save_review(db: Session, user, surah: int, from_ayah: int, tracker: LiveRecitation):
    review = tracker.snapshot()
    if not tracker.cursor:
        return {"session_id": None, **review}
    session = RecitationSession(
        user_id=user.id, surah=surah, ayah=from_ayah, mode="continuous",
        status="uncertain" if tracker.uncertain or tracker.pending else "ok",
        transcription=review["transcription"], total_words=tracker.cursor,
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
        reference = load_reference().get(start.surah, {})
        if start.from_ayah not in reference:
            raise ValueError("Unknown starting ayah")
        if not hasattr(transcriber, "transcribe_words"):
            raise ValueError("This backend does not support live speech recognition")
        tracker = LiveRecitation({a: row["text"] for a, row in reference.items()
                                  if a >= start.from_ayah})
        # The client keeps its microphone off until the model has loaded.
        device = await asyncio.to_thread(transcriber.prepare_stream)
        await socket.send_json({"type": "ready", "device": device, "sample_rate": SAMPLE_RATE,
                                "engine": getattr(transcriber, "engine", "test")})
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
