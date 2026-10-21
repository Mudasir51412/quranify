# Quranify — AI Quran Tutor (MVP, built from scratch)

Listens to a user's recitation of one Ayah and gives instant feedback:
skipped words + basic Harakat mistakes (Fatha / Kasra / Damma), with
correction audio. Built from the Quranify final report (Faizan Ahmed &
Hafiz Talal Zeb Abbasi, COMSATS) — see `MVP-Build-Plan.md` for scope
and for every tech change from the report, with reasons.

## Status — Step 1+2 done: repo + AI core

| Component | State |
|---|---|
| Text normalization (`fix_whisper`) | ✅ implemented + tested |
| Skipped-word detection (SequenceMatcher + fuzzy 0.70) | ✅ implemented + tested |
| Harakat comparison (consonant-aligned, tanween grouped) | ✅ implemented + tested |
| Audio guardrails (silence / empty / NaN / Inf) | ✅ implemented + tested |
| Combined pipeline (`analyze_recitation`) | ✅ implemented + tested |
| Whisper model benchmark v0 | ✅ done — see below |
| FastAPI + auth + DB (SQLite dev / PostgreSQL via DATABASE_URL) | ✅ done |
| Huffaz continuous mode (`/analyze_continuous`) | ✅ done — confirmed-pointer scoring |
| Gamification (points / levels / 7 badges, computed) | ✅ done |
| Offline sync endpoint (idempotent, FR-18) + reading position | ✅ done |
| Flutter app (complete, all 8 modules) | ✅ built — see below |
| Docker Compose deployment (API + PostgreSQL) | ✅ `docker-compose.yml` |

**Backend tests: 85 passed** (AI core + API + continuous + gamification + sync).

## API (FastAPI, `backend/app/`)

Run: `cd backend && uvicorn app.main:app --reload` → docs at `/docs`.

- `POST /auth/register` · `POST /auth/login` · `GET /auth/me` · `POST /auth/logout`
  — PBKDF2 password hashing + JWT, actually implemented and tested
- `GET /quran/surahs` · `GET /quran/surah/{num}` · `GET /available_surahs`, `GET /surah/{num}` (report aliases)
- `POST /analyze` (auth, multipart audio + surah + ayah) — guardrails reject
  invalid audio *before* scoring and save nothing for it; results persist
  as sessions + mistake records
- `GET /correction_audio?surah=&ayah=&word=` — ayah-local word contract with
  prev/next context; word-level MP3 asset still pending (response says so
  honestly and gives the Ayah audio URL meanwhile)
- `GET /history` · `GET /history/{id}` (another user's session = 404, no leak)
- `GET /progress` · `GET /streak` — computed from real sessions only
- `GET /daily` — Ayah + Hadith of the day (`data/daily_content.json`)
- `POST /analyze_continuous` — Huffaz mode: recite a window of up to 10
  Ayahs; scoring stops at the confirmed-position pointer; reports
  skipped words, skipped whole Ayahs, and Harakat errors per Ayah
- `GET /gamification` — points, level, 7 rule-based badges, completed
  Surahs — all computed from session history, nothing stored
- `GET /home` — one-call aggregate for the app home screen
- `PATCH /auth/me` · `PUT /auth/reading-position` — profile settings
  (name, mode, notification preference) and last reading position
- `POST /sync/sessions` — offline session upload (FR-18 contract),
  idempotent per client UUID, insert-only, never overwrites
- Transcriber is pluggable: tests inject a fake; production loads the
  benchmarked Whisper checkpoint lazily from the local HF cache

## Benchmark v0 — EveryAyah smoke test (2026-10-21)

`basharalrfooh/whisper-small-quran` via transformers on CPU, 10 Ayahs
recited by Alafasy, ground truth = our Tanzil corpus.
Files: `benchmarks/v0_everyayah_smoke.json` / `.md`, repro:
`scripts/benchmark_model.py`.

- **Normalized CER 0.50% · normalized WER 9.2%** (after the U+0670 fix below)
- Model output is **fully diacritized** on all samples → Harakat checking
  works directly from its transcription
- Pipeline verdicts on this professional reciter: **10/10 "ok", zero
  false skips, zero false Harakat errors**
- Inference on this 2-core VM: 7.6–13.5 s/Ayah with transformers —
  production needs faster-whisper (target 3–5 s), as planned
- ⚠️ In-distribution smoke test only (EveryAyah is the model's training
  distribution). Held-out benchmark v1 (Buraaq / real learner recordings,
  including deliberate-error cases) is still owed.

## Resolved open point — superscript alef (U+0670)

Was: removed in normalization (report's Algorithm 1). Benchmark data
showed the model writes imla'i spelling (العالمين, أعطيناك), so U+0670
now maps **to** alef. Effect on v0: WER 12.5% → 9.2%, CER 1.26% → 0.50%.
Trade-off (الرحمن → الرحمان on the reference side) is absorbed by fuzzy
matching and produced no false skips. Covered by tests 04 + 13.

## Cloning this repo — one setup note

Binary platform assets (launcher icons, `gradle-wrapper.jar`, web icons)
are not stored in git. After cloning, regenerate the missing platform
files once from `mobile/`:

```
flutter create . --platforms=web,android
```

This only *adds* missing platform files — your `lib/` code and
`AndroidManifest.xml` (which carries the mic/internet permissions) are
already in the repo; check `git status` afterwards and restore the
manifest from git if the generator touched it
(`git checkout -- android/app/src/main/AndroidManifest.xml`).

## Flutter app (`mobile/`)

Complete app covering all 8 report modules:

- **Auth** — login / register (Normal or Hafiz chosen at signup)
- **Home** — greeting, 🔥 streak chip, level + points progress, continue
  reading, Ayah & Hadith of the day
- **Quran** — searchable list of 114 Surahs; Surah view with Verse-by-Verse
  and Reading (continuous Mushaf-style) views, font-size control,
  listen-to-Ayah, save reading position, and a **Hide text (Hifz test)**
  mode that masks Ayahs until tapped
- **Recite** — Single Ayah mode and **Continuous (Huffaz) mode**
  (window of up to 10 Ayahs, confirmed-position result with per-Ayah
  chips and skipped-Ayah flags); results highlight skipped words in red
  and Harakat words in orange, with plain Zabar/Zair/Paish wording and
  one-tap correction playback
- **Progress** — overview stats, mistakes-by-type, accuracy trend,
  badges grid, full session history with detail dialogs
- **Profile** — name/mode/notification settings, API URL override
  (for emulator/LAN testing), offline notes, sign out
- **Offline** — Quran lists/texts opened once are cached on-device and
  stay readable offline; analysis honestly requires the server in this
  version (on-device ASR remains future work, as in the report)

Run it:

```
cd mobile
flutter pub get
flutter run --dart-define=API_URL=http://10.0.2.2:8000   # Android emulator
flutter test        # unit + widget tests
flutter build web   # VM-verified build target
```

## Tests — backend 85 passed; Flutter tests in `mobile/test/`

The suite reproduces the report's 50 cases (§5.1–5.4). Their run was
47/50 with a footer wrongly claiming 50/50. Ours is 55/55 (50 cases +
reference-loader + full-corpus + U+0670 decision tests), including
fixes for all 3 of their failures:

- **D01 / case 3 — Damma normalization:** all harakat now stripped by one
  explicit diacritic set; no per-vowel drift.
- **D02 / case 49 — empty reference:** explicit `rejected / EMPTY_REFERENCE`
  before scoring, never a scored mismatch.
- **D03 / case 50 — unvocalized transcription:** returns
  `uncertain / INSUFFICIENT_VOWEL_EVIDENCE` (retry), never a false pass.

Counts come from pytest. Nothing is hand-written.

## Run it

```bash
cd backend
pip install -r requirements.txt   # numpy + pytest for the AI core
python -m pytest tests/ -q
# or from repo root:
bash scripts/verify.sh
```

## Layout

```
backend/app/ai/   normalization, skip_detection, harakat,
                  audio_guardrails, pipeline, reference
backend/tests/    the 50-case suite + loader test
data/             sample_quran.json (Al-Fatiha + Al-Ikhlas, Tanzil text)
                  — full corpus comes from the data-pipeline step
mobile/           Flutter app (next steps)
scripts/verify.sh the harness
```

## Full reference corpus

`data/quran_reference.json` — all 114 Surahs / 6,236 Ayahs (Tanzil
Uthmani via AlQuran Cloud), built by `scripts/build_reference.py`.
Bismillah is stored per-Surah, not prefixed onto Ayah 1 (112 prefixes
stripped, incl. the typo'd بِّسْمِ variants in Surahs 95/97); Surah 1
keeps it as its Ayah 1. Corpus tests in `tests/test_full_reference.py`.
