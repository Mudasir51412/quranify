"""Rehearse a real WebSocket with timed PCM, the real model, and an isolated DB.

Downloads four short reference clips (training-distribution smoke test). This
does not substitute for a physical-phone/microphone accuracy rehearsal.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
import wave

import httpx
import numpy as np
from websockets.asyncio.client import connect

ROOT = Path(__file__).resolve().parents[1]


def fixtures(ffmpeg):
    cache = ROOT / "benchmarks" / "audio_cache"
    cache.mkdir(exist_ok=True)
    clips = []
    for ayah in range(1, 5):
        stem = f"112{ayah:03d}"
        mp3, wav = cache / f"{stem}.mp3", cache / f"{stem}.wav"
        if not mp3.exists():
            request = urllib.request.Request(
                f"https://everyayah.com/data/Alafasy_128kbps/{stem}.mp3",
                headers={"User-Agent": "quranify-stream-smoke/1.0"})
            with urllib.request.urlopen(request, timeout=60) as response:
                mp3.write_bytes(response.read())
        if not wav.exists():
            subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(mp3),
                            "-ar", "16000", "-ac", "1", str(wav)], check=True)
        with wave.open(str(wav)) as source:
            clips.append(source.readframes(source.getnframes()))
        clips.append(bytes(16000 // 4 * 2))
    return b"".join(clips)


async def rehearse(base, pcm):
    async with httpx.AsyncClient() as client:
        for _ in range(80):
            try:
                if (await client.get(f"{base}/health")).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.25)
        auth = await client.post(f"{base}/auth/register", json={
            "email": f"stream-{uuid.uuid4()}@test.local", "password": str(uuid.uuid4())})
        auth.raise_for_status()
        token = auth.json()["token"]
    async with connect(base.replace("http", "ws") + "/recite/live", max_size=2**20) as ws:
        await ws.send(json.dumps({"token": token, "surah": 112, "from_ayah": 1}))
        ready = json.loads(await asyncio.wait_for(ws.recv(), 120))
        assert ready["type"] == "ready", ready
        print(json.dumps(ready), flush=True)
        started = time.perf_counter()
        updates = []
        stop_time = None

        async def send():
            nonlocal stop_time
            for offset in range(0, len(pcm), 3200):  # 100 ms PCM frames.
                await ws.send(pcm[offset:offset + 3200])
                await asyncio.sleep(0.1)
            # Include a normal pause to stabilize the final spoken word.
            for _ in range(15):
                await ws.send(bytes(3200))
                await asyncio.sleep(0.1)
            stop_time = time.perf_counter() - started
            await ws.send(json.dumps({"type": "stop"}))

        sender = asyncio.create_task(send())
        try:
            async for message in ws:
                event = json.loads(message)
                if event["type"] == "error":
                    raise RuntimeError(event)
                if event["type"] == "feedback":
                    row = {key: event[key] for key in ["scored_words", "current_ayah", "inference_ms", "audio_backlog_ms"]}
                    row["at_seconds"] = round(time.perf_counter() - started, 3)
                    updates.append(row)
                    print(json.dumps(row), flush=True)
                if event["type"] == "finished":
                    await sender
                    assert any(u["scored_words"] > 0 and u["at_seconds"] < stop_time for u in updates)
                    assert event["completed"], event
                    assert event["session_id"] is not None
                    return {"ready": ready, "updates": updates, "stop_at_seconds": stop_time,
                            "review": event, "caveat": "Reference audio; no physical-phone rehearsal"}
        finally:
            if not sender.done():
                sender.cancel()
            await asyncio.gather(sender, return_exceptions=True)
    raise RuntimeError("Socket closed without a review")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ffmpeg", default="ffmpeg")
    args = parser.parse_args()
    pcm = fixtures(args.ffmpeg)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="quranify-stream-") as directory:
        environment = dict(os.environ, DATABASE_URL=f"sqlite:///{Path(directory) / 'smoke.db'}",
                           HF_HUB_OFFLINE="1", QURANIFY_DEVICE="auto")
        with open(Path(directory) / "server.log", "w", encoding="utf-8") as log:
            process = subprocess.Popen([
                sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
                "--port", str(port)], cwd=ROOT / "backend", env=environment,
                stdout=log, stderr=log,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            try:
                result = asyncio.run(rehearse(f"http://127.0.0.1:{port}", pcm))
                target = ROOT / "benchmarks" / "live_websocket_smoke.json"
                target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"Saved {target}", flush=True)
            except Exception:
                print((Path(directory) / "server.log").read_text(encoding="utf-8"), flush=True)
                raise
            finally:
                if os.name == "nt":
                    # venv python.exe can launch a child interpreter on Windows.
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                # Windows releases inherited log handles shortly after the
                # interpreter exits; allow that before TemporaryDirectory cleanup.
                time.sleep(0.5)


if __name__ == "__main__":
    main()
