#!/usr/bin/env python3
"""
Build the full Quran reference corpus: data/quran_reference.json

Source: AlQuran Cloud API edition `quran-uthmani`, which serves the
Tanzil Uthmani text (Tanzil v1.1) — the same reference text family the
Quranify report specifies. Endpoint:
    https://api.alquran.cloud/v1/quran/quran-uthmani

Output structure matches data/sample_quran.json:
    {"source": ..., "surahs": {"1": {"name_ar":..., "name_en":...,
                                     "ayahs": {"1": "...", ...}}, ...}}

Verification (asserted, not assumed):
- exactly 114 surahs
- exactly 6,236 ayahs in total
- well-known ayahs spot-checked by the test suite (1:1, 2:255, 112:1)

Usage: python scripts/build_reference.py
"""
import json
import sys
import urllib.request
from pathlib import Path

API_URL = "https://api.alquran.cloud/v1/quran/quran-uthmani"
OUT = Path(__file__).resolve().parents[1] / "data" / "quran_reference.json"
EXPECTED_SURAHS = 114
EXPECTED_AYAHS = 6236


def main() -> int:
    print(f"Fetching {API_URL} ...")
    req = urllib.request.Request(API_URL, headers={"User-Agent": "quranify-mvp/0.1"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        payload = json.load(resp)

    surahs_in = payload["data"]["surahs"]
    assert len(surahs_in) == EXPECTED_SURAHS, f"surahs: {len(surahs_in)}"

    # The API prefixes Bismillah onto Ayah 1 of every Surah except 1 and 9.
    # For per-Ayah scoring that prefix must NOT be part of Ayah 1's text:
    # a user reciting "Qul huwallahu ahad" (112:1) would otherwise be
    # falsely flagged for skipping the Bismillah words. We strip it from
    # the Ayah text and store it once per Surah instead. Surah 1 keeps it
    # (there Bismillah IS Ayah 1); Surah 9 has none.
    bismillah = surahs_in[0]["ayahs"][0]["text"].lstrip("\ufeff").strip()
    # Compare by diacritic-stripped words: Surahs 95 & 97 carry a typo'd
    # prefix in this API (extra shadda: بِّسْمِ), so an exact-string match
    # misses them. The prefix is always the first 4 tokens.
    import re as _re
    _strip = lambda s: _re.sub(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u0640]", "", s)
    bismillah_norm = _strip(bismillah).split()

    surahs: dict[str, dict] = {}
    total_ayahs = 0
    stripped_prefixes = 0
    for s in surahs_in:
        num = s["number"]
        ayahs = {}
        for a in s["ayahs"]:
            text = a["text"].lstrip("\ufeff").strip()
            if num not in (1, 9) and a["numberInSurah"] == 1:
                tokens = text.split()
                if [_strip(t) for t in tokens[:4]] == bismillah_norm or tokens[:4] == bismillah_norm:
                    text = " ".join(tokens[4:])
                    stripped_prefixes += 1
            ayahs[str(a["numberInSurah"])] = text
        total_ayahs += len(ayahs)
        surahs[str(num)] = {
            "name_ar": s["name"],
            "name_en": s["englishName"],
            "ayah_count": len(ayahs),
            "bismillah": None if num == 9 else bismillah,
            "ayahs": ayahs,
        }
    assert total_ayahs == EXPECTED_AYAHS, f"ayahs: {total_ayahs}"
    assert stripped_prefixes == 112, f"bismillah prefixes stripped: {stripped_prefixes}"

    doc = {
        "source": "Tanzil Uthmani text (v1.1) via AlQuran Cloud API edition 'quran-uthmani'",
        "source_url": API_URL,
        "surah_count": len(surahs),
        "ayah_count": total_ayahs,
        "surahs": surahs,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)
    print(f"Wrote {OUT} — {len(surahs)} surahs, {total_ayahs} ayahs, "
          f"{OUT.stat().st_size/1024:.0f} KiB")
    print("Spot checks:")
    print("  1:1  ", surahs["1"]["ayahs"]["1"])
    print("  112:1", surahs["112"]["ayahs"]["1"])
    print("  2:255 starts", surahs["2"]["ayahs"]["255"][:40], "...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
