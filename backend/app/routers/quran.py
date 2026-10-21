"""Quran browsing routes — served from the bundled Tanzil corpus."""
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException

from ..ai.reference import load_reference

router = APIRouter(prefix="/quran", tags=["quran"])


@lru_cache(maxsize=1)
def _corpus():
    return load_reference()


@lru_cache(maxsize=1)
def _raw():
    import json
    path = Path(__file__).resolve().parents[3] / "data" / "quran_reference.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


@router.get("/surahs")
def list_surahs():
    raw = _raw()
    ref = _corpus()
    out = []
    for num in sorted(ref):
        meta = (raw or {}).get("surahs", {}).get(str(num), {})
        out.append({
            "number": num,
            "name_ar": meta.get("name_ar", ""),
            "name_en": meta.get("name_en", ""),
            "ayah_count": len(ref[num]),
        })
    return {"surahs": out, "count": len(out)}


@router.get("/available_surahs")
def available_surahs():
    """Report-compatible alias (Table 4.6)."""
    return {"available_surahs": sorted(_corpus().keys())}


@router.get("/surah/{num}")
def get_surah(num: int):
    ref = _corpus()
    if num not in ref:
        raise HTTPException(404, "Surah not found")
    raw = _raw()
    meta = (raw or {}).get("surahs", {}).get(str(num), {})
    ayahs = [{"ayah": a, "text": ref[num][a]["text"],
              "word_count": ref[num][a]["word_count"]}
             for a in sorted(ref[num])]
    return {
        "number": num,
        "name_ar": meta.get("name_ar", ""),
        "name_en": meta.get("name_en", ""),
        "bismillah": meta.get("bismillah"),
        "ayahs": ayahs,
    }
