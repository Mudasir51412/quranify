"""Ayah & Hadith of the Day (report Module 4) — deterministic rotation
by day of year over a curated list; ayah text comes from the corpus."""
import json
from datetime import date
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter

from ..ai.reference import load_reference

router = APIRouter(tags=["daily"])


@lru_cache(maxsize=1)
def _entries() -> list[dict]:
    path = Path(__file__).resolve().parents[3] / "data" / "daily_content.json"
    return json.loads(path.read_text(encoding="utf-8"))["entries"]


@router.get("/daily")
def daily():
    entries = _entries()
    entry = entries[date.today().timetuple().tm_yday % len(entries)]
    ref = load_reference()
    text = ref[entry["surah"]][entry["ayah"]]["text"]
    return {
        "date": date.today().isoformat(),
        "ayah": {"surah": entry["surah"], "ayah": entry["ayah"],
                 "text": text, "theme": entry["theme"]},
        "hadith": {"text": entry["hadith"], "source": entry["hadith_source"]},
    }
