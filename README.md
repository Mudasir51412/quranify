# Quranify — AI Quran Tutor (MVP, built from scratch)

Records one Ayah at a time, with a Hifz toggle to hide the displayed text.
After pressing Pause, the recording is uploaded for feedback:
**Missed** words and **Wrong** words/basic Harakat feedback, with
phrase correction audio and targeted retries. Built from the Quranify final report (Faizan Ahmed &
Hafiz Talal Zeb Abbasi, COMSATS) — see `MVP-Build-Plan.md` for scope
and for every tech change from the report, with reasons.

## Recite and Hifz

The Recite tab loads the Arabic passage before the microphone starts. Choose a
Surah and starting Ayah. All remaining Ayahs are displayed, with text visible by
default even for Hafiz accounts. Optionally press **Hifz · Hide text**.
Press **Recite beside the Ayah** you want to practice, read that Ayah, then press
**Pause**. Pause ends the clip and uploads it to `POST /analyze`. Feedback appears
directly beneath that Ayah; **Try again** starts a fresh attempt for that Ayah.
For individual issues, **Try this phrase** records only the displayed short phrase.
Its **Listen** button plays that same phrase using verified reference word timings.

- Missed words appear faintly; wrong words receive a light red highlight.
  In Hifz these words are revealed after analysis; other reference words stay hidden.
- Only one recording or analysis can run at a time. There is no live analysis,
  automatic Ayah advance, or continuous listening in the app.
- A full attempt checks the selected Ayah. A phrase retry checks only its inclusive,
  zero-based `word_start` / `word_end` range; words outside that range are not scored.
- Immediate repetitions and complete phrase restarts are allowed. A correct
  repeated word replaces its preceding attempt. Split/stretched tokens with insufficient evidence request
  another attempt rather than producing a false word-error highlight.
- Unreliable recognition says **Please try this phrase again**. There is no
  "unclear" word category. Unresolved words are excluded from accuracy scoring;
  a completely unresolved attempt creates no scored session.
  The summary includes **1 word to retry** (or its plural), identifies each target
  word, and uses a dotted underline for those targets. A retry-only result does
  not show a misleading **0 missed · 0 wrong** all-clear summary. Confirmed
  missed/wrong counts and pending retries appear together when both exist.
- Shadda feedback describes missing or unexpected consonant doubling. It does
  not report identical expected/heard vowels as if the vowel itself were wrong.
- Audio is recorded as a 16 kHz mono WAV. Temporary clips are removed after submission.
- Upload/analysis requests time out after two minutes and allow another attempt.
- Leaving the Recite tab or backgrounding cancels an unfinished recording without
  submitting it. An analysis already submitted may finish in the background.
- Retrying an Ayah replaces its displayed feedback; other Ayahs keep their results.
  Phrase retries preserve feedback while recording, clear only successfully
  reassessed errors, and keep unresolved errors elsewhere. Historical attempts
  remain separate records; phrase practice does not earn a perfect-Ayah bonus.
- Listen requires public reference timing metadata (cached on the backend). If
  matching timings are unavailable, it reports a playback error without playing
  the entire Ayah. Practice phrases include neighboring context and at most five words.

Use the existing `run_backend.bat` launcher, or run this from `backend/`:

```powershell
.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

In the app's Profile connection settings, use your PC's current LAN URL,
not the phone's localhost. For the optimized local model, run these once
from the repository root:

```powershell
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
# For a compatible NVIDIA GPU, install a CUDA-enabled PyTorch build:
backend\.venv\Scripts\python.exe -m pip install torch==2.11.0 --index-url https://download.pytorch.org/whl/cu128
backend\.venv\Scripts\python.exe scripts\prepare_live_model.py
```

The conversion uses the same `basharalrfooh/whisper-small-quran` checkpoint and
keeps its Arabic tokenizer. Generated weights live in ignored `models/`, with a
completion marker so partially prepared weights are never auto-selected.
`QURANIFY_ENGINE=auto` selects the prepared faster-whisper model, otherwise the
Transformers model. `QURANIFY_DEVICE=auto` selects CUDA when available, otherwise
CPU. Explicit engine values are `faster-whisper` and `transformers`; explicit
device values are `cuda` and `cpu`. Restart the backend after changing these.

The server now loads and warms the primary decoder before announcing startup
completion, so the first recitation does not have to initialize the model.
Startup itself takes several seconds. `/health` includes the startup inference
status, selected engine and device; a warmed GPU reports `ready` and `cuda`.
Set `QURANIFY_WARMUP=0` only when intentionally using lazy model loading.
Normalized Quran reference data is cached (and refreshed when the source file
changes). Native 16 kHz mono PCM16 phone recordings decode directly in memory;
compressed or differently formatted uploads still use ffmpeg.

`scripts/benchmark_analysis_latency.py` records per-stage upload latency against
an isolated database. Saved before/after measurements are in
`benchmarks/analysis_latency_baseline.json` and `benchmarks/analysis_latency_optimized.json`.
On this GPU, short professional reference Ayahs improved from a 436 ms median
to 255 ms after startup warmup; the first upload fell from 5.55 s to 287 ms.
The optimized run spent 7.05 s warming the server before accepting requests.
These timings exclude phone recording finalization and Wi-Fi upload, and do not
predict latency for longer or difficult learner recordings. Error confirmation
and retry checks remain enabled.

The backend still includes the experimental streaming and continuous endpoints
for compatibility; the mobile Recite tab does not use them. GPU selection also
applies to single-Ayah uploads. The model can misrecognize vowels; highlights
are feedback to review, not a guaranteed pronunciation diagnosis.
The Recite endpoint uses the original unprompted transcription and whole-phrase
comparison path again. It does not use a second decode to fill omissions or
erase errors, and uncertainty on one word cannot suppress mistakes elsewhere.
Leniency is limited to immediate repetitions, anchored token splits, repeated
letter spellings and known rendering differences. Changed spellings and isolated
phrase-final vowel discrepancies request a retry rather than a false pass.
Explicit omissions and available short-vowel/shadda errors remain flagged.
Partially vocalized ASR text follows the original comparison behavior; a fully
unvocalized word still needs another attempt. The recognizer is never prompted
with the expected Ayah. This remains ASR-derived feedback, not a pronunciation
accuracy guarantee.

`scripts/smoke_fatiha_feedback.py` checks professional Al-Fatiha Ayahs 5–7 and
synthetic omitted/replaced words, including which exact word was edited.
`benchmarks/fatiha_feedback_smoke.json` includes both results and remaining
recognition uncertainty; it is not an evaluation of learner speech accuracy.

`scripts/smoke_ayah_upload.py` exercises the real WAV upload, decoding, GPU model,
feedback, history, and silence rejection with a temporary database and cached
reference clips. Results are saved in `benchmarks/ayah_upload_smoke.json`.
Professional reference audio does not establish learner pronunciation accuracy.

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

Run backend regression checks with `backend/.venv/Scripts/python.exe -m pytest backend/tests -q`.
The suite covers AI core, practice retries, phrase audio, API, continuous/live streaming,
gamification and sync.

## API (FastAPI, `backend/app/`)

Run: `cd backend && uvicorn app.main:app --reload` → docs at `/docs`.

- `POST /auth/register` · `POST /auth/login` · `GET /auth/me` · `POST /auth/logout`
  — PBKDF2 password hashing + JWT, actually implemented and tested
- `GET /quran/surahs` · `GET /quran/surah/{num}` · `GET /available_surahs`, `GET /surah/{num}` (report aliases)
- `POST /analyze` (auth, multipart audio + surah + ayah) — guardrails reject
  invalid audio *before* scoring and save nothing for it; results persist
  as sessions + mistake records
- `GET /correction_audio?surah=&ayah=&word=&word_start=&word_end=` — ayah-local
  phrase context plus `audio_url`, `start_ms`, `end_ms` from verified public
  Alafasy word timings. Returns 503 if the phrase cannot be isolated.
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
- **Recite** — full passage from the starting Ayah, per-Ayah Recite/Pause controls,
  optional Hifz, feedback after submission with faint skipped-word and light red
  vowel highlights, plus independent retries and reference audio
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

## Tests — backend 146 passed; Flutter 33 passed

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
