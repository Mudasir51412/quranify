"""Quranify API — FastAPI application entrypoint.

Run:  uvicorn app.main:app --reload   (from backend/)
Docs: /docs
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db import Base, engine
from .routers import analyze, auth, complete, daily, progress, quran

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Quranify API", version="0.1.0",
              description="AI Quran Tutor — recitation analysis API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # dev; tighten per-deployment for production
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(quran.router)
app.include_router(analyze.router)
app.include_router(progress.router)
app.include_router(daily.router)
app.include_router(complete.router)


@app.get("/health")
def health():
    return {"status": "ok", "service": "quranify-api", "version": "0.1.0"}


# Report-compatible top-level alias: GET /available_surahs
@app.get("/available_surahs")
def available_surahs_root():
    return quran.available_surahs()


@app.get("/surah/{num}")
def surah_root(num: int):
    return quran.get_surah(num)
