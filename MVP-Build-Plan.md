# Quranify — MVP Build Plan (from scratch)
**For:** Faizan Ahmed & Hafiz Talal Zeb Abbasi's project, via Arsalan
**Date:** 2026-10-21
**Decisions locked:** Build from scratch · MVP first · Tech can differ from report if better

---

## 1. MVP Scope — what "done" means

### IN (MVP v1)
1. **Auth** — register / login / logout, JWT, hashed passwords
2. **Quran browsing** — Surah list (114), Ayah-by-Ayah view with full diacritized Tanzil text + English translation, last-reading position saved
3. **Normal Mode recitation (core)** — record ONE Ayah (start / pause / stop), upload, get analysis in <5s
4. **Skipped-word detection** — SequenceMatcher alignment + fuzzy threshold 0.70 (from report, proven)
5. **Harakat detection** — Fatha / Kasra / Damma only, consonant-aligned comparison, second Whisper pass with neutral prompt (report's key lesson). If vowel evidence is insufficient → return "uncertain / retry", NOT "correct" (fixes report defect D03 / case 50)
6. **Feedback UI** — mistaken words highlighted red, tap a word → expected vs heard vowel, play correction audio in context (prev word → correct word → next word)
7. **Mistake history + simple dashboard** — sessions per Surah/Ayah, accuracy trend, mistakes by type (skipped / harakat), review old mistakes, practice-again flow
8. **Streak** — daily recitation streak count + gentle reminder logic (backend count only in MVP)
9. **Ayah & Hadith of the Day** — curated static list, rotates by date

### OUT (Phase 2, explicitly not MVP)
- Huffaz continuous mode (`/analyze_continuous`, rolling buffer)
- Offline on-device ASR / quantized model
- Advanced Tajweed (Madd, Ghunna, Qalqalah, Ikhfa) — dashboard must NOT show these until detectors exist
- Gamification badges / levels / points beyond streak
- 16-line Mushaf view
- Tafseer / translation comparison

---

## 2. Tech Stack — chosen, with reasons for every change from the report

| Layer | Report said | We will use | Why it's better |
|---|---|---|---|
| Mobile | Flutter 3.38 | **Flutter (keep)** | Best Arabic / Mushaf rendering, Talal already knows it, one codebase for Android+iOS, real APK — not a dev tunnel |
| Backend | FastAPI | **FastAPI (keep)** | Python is mandatory for Whisper ecosystem; async, auto /docs contract |
| ASR inference | HF Transformers Whisper (PyTorch) | **faster-whisper (CTranslate2)** | Same weights, ~4x faster, ~half VRAM, INT8 runs well on CPU — makes a cheap VPS viable instead of needing a GPU server for MVP |
| ASR model v0 | Train whisper-small from base | **Start: `basharalrfooh/whisper-small-quran`** — WER 10.1% normal / 9.9% pro, CER 3.3%, trained on EveryAyah (64 reciters, 399k verses) | Better than the report's own fine-tune (WER 12.89%, CER 6.82%) on day 1 with zero training time. Gives us a working MVP immediately |
| ASR model v1 | — | **Then fine-tune our own whisper-small on Buraaq/quran-md** (4,988/1,247 split recipe from report, Epoch-4 checkpoint rule) and A/B it against v0 | We ship first, train second. Own model = own asset, versioned on HF Hub |
| Database | MongoDB | **PostgreSQL** (SQLite for local dev) | Data is relational: User → Session → Mistakes. SQL aggregation powers the dashboard honestly. Stronger auth integrity, Alembic migrations. Free on Neon/Supabase |
| Quran text | Tanzil | **Tanzil (keep)** + bundled JSON in repo/app | Verified text, no API dependency, works offline for reading |
| Correction audio | `.pkl` files on personal Google Drive | **MP3/Opus files, served as static assets / object storage, indexed by (surah, ayah, word_index)** — word audio from Buraaq/quran-md-words (77,429 words, 30 reciters) | Fixes the report's biggest fragility. Ayah-local index is the contract (report §4.4 lesson) |
| Deployment | Colab + ngrok | **Docker Compose, single VPS** (backend + Postgres + model in one compose) | Reproducible, pinned deps, real URL for the phone app. No ngrok, no Colab session deaths |
| Auth/Security | JWT etc. (diagrams only) | **JWT + bcrypt + HTTPS + input validation, actually implemented + tested** | Report Ch 4.3 admits theirs was never built. Ours ships with tests |

---

## 3. Architecture (MVP)

```
Flutter app
  ├─ record audio (16kHz mono WAV/M4A)
  └─ HTTPS ──► FastAPI
                ├─ /auth/*            register, login, me
                ├─ /quran/surahs      list + /quran/surah/{num}
                ├─ /analyze           POST audio + surah + ayah
                │     ├─ guardrails: silence / empty / NaN / too-short → reject, no score
                │     ├─ faster-whisper pass 1 (no prompt) → transcription
                │     ├─ normalize (fix_whisper) → align vs reference → skips
                │     ├─ faster-whisper pass 2 (neutral prompt, diacritics) → harakat compare
                │     └─ save session + mistakes ──► PostgreSQL
                ├─ /correction_audio  GET ?surah=&ayah=&word=  (ayah-local index)
                ├─ /history, /progress, /streak
                └─ /daily             ayah + hadith of the day
```

## 4. Build order (each step verifiable before the next)

1. **Repo + harness** — monorepo: `backend/`, `mobile/`, `data/`, verify script + pytest, like a real project from day 1
2. **Data pipeline** — download Tanzil + Buraaq metadata, build `QURAN_REF[surah][ayah]` (diacritized + stripped), extract word-audio index
3. **AI core as a library first (no API yet)** — normalization, skip detection, harakat, guardrails + unit tests reproducing the report's 50 cases, with the 3 known failures FIXED (Damma case 3, empty-ref 49, unvocalized 50 → uncertain)
4. **Model benchmark** — run v0 model on held-out Buraaq samples, report real WER/CER ourselves; don't trust any README number blindly
5. **FastAPI** — endpoints above, auth, DB models, integration tests (the F01–F12 / I01–I05 the report never ran)
6. **Flutter MVP** — 5 screens only: Home (daily + continue), Quran, Recite/Result, Dashboard/History, Profile
7. **Docker deploy + phone E2E** — real device, real network, latency measured against the 3–5s target

## 5. Honesty rules (carried over from the report's lessons)
- No dashboard number that isn't computed from real sessions
- No Tajweed category shown until its detector is tested
- "Uncertain" is a valid result — absence of evidence ≠ correct recitation
- Test summary counts derived from cases, never hand-written (report's 50/50 footer bug)

## 6. Open question for Phase 2 planning only (not blocking MVP)
- Fine-tune budget: Colab free T4 worked for them (7 epochs, staged). We can do the same, or a short paid GPU run for v1 model after MVP ships.
