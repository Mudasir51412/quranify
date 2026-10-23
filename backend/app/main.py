"""Quranify API — FastAPI application entrypoint.

Run:  uvicorn app.main:app --reload   (from backend/)
Docs: /docs
"""
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool

from .db import Base, engine
from .ai.reference import load_reference
from .config import settings
from .routers import analyze, auth, complete, daily, live, progress, quran

Base.metadata.create_all(bind=engine)


def prepare_inference(app: FastAPI):
    load_reference()
    app.state.inference = {"status": "not_warmed"}
    if not settings.warm_model_on_startup:
        return
    provider = app.dependency_overrides.get(analyze.get_transcriber, analyze.get_transcriber)
    try:
        model = provider()
        app.state.inference.update(engine=getattr(model, "engine", "custom"),
                                   device=getattr(model, "device", "unknown"))
        warmup = getattr(model, "warmup", None)
        if warmup is not None:
            logging.getLogger("uvicorn.error").info("Warming recitation model before API readiness...")
            device = warmup()
            app.state.inference.update(status="ready", device=device)
            logging.getLogger("uvicorn.error").info("Recitation model ready on %s", device)
    except Exception as exc:
        app.state.inference["status"] = "unavailable"
        logging.getLogger("uvicorn.error").warning(
            "Recitation warmup failed (%s); browsing/auth remain available", type(exc).__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await run_in_threadpool(prepare_inference, app)
    yield

app = FastAPI(title="Quranify API", version="0.1.0",
              description="AI Quran Tutor — recitation analysis API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # dev; tighten per-deployment for production
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(quran.router)
app.include_router(analyze.router)
app.include_router(live.router)
app.include_router(progress.router)
app.include_router(daily.router)
app.include_router(complete.router)


@app.get("/health")
def health():
    return {"status": "ok", "service": "quranify-api", "version": "0.1.0",
            "inference": getattr(app.state, "inference", {"status": "not_warmed"})}


# Report-compatible top-level alias: GET /available_surahs
@app.get("/available_surahs")
def available_surahs_root():
    return quran.available_surahs()


@app.get("/surah/{num}")
def surah_root(num: int):
    return quran.get_surah(num)
