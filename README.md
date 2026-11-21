# Quranify — AI Quran Tutor (MVP, built from scratch)

Streams a selected Quran passage for live word feedback in Normal and Hifz
modes. Built from the Quranify final report (Faizan Ahmed &
Hafiz Talal Zeb Abbasi, COMSATS) — see `MVP-Build-Plan.md` for scope
and for every tech change from the report, with reasons.

## Recite and Hifz

Choose a surah, starting ayah, and mode. The Recite tab displays the rest of
the surah in one right-to-left passage with round ayah markers. Normal shows
the text up front. Hifz reveals recognized words and confirmed mistake
targets as you recite.

Choose **Recitation difficulty** under **Profile → Settings**. The app uses
that choice for the whole Normal or Hifz session, including after Pause,
reference playback, and targeted retries. **Expert** is the default and
uses the original scoring and feedback.

- **Beginner** can verify stable borderline exact words and common single
  spelling changes when timed exact words establish their position. It can
  use one exact neighbor at a unique position for a well-supported word,
  including short words. A borderline near-match instead needs exact speech
  on both sides in the same ayah. It can repair exact word joins and splits
  with corroboration, and can bridge a timed ayah handoff when the words on
  both sides establish the boundary. An isolated retry can pass on its first
  supported attempt for exact words and selected longer-word variations.
- **Intermediate** typically needs two exact neighbors or a separate
  supported repeat. A configured consonant substitution on a word of four
  or more letters needs exact speech on both sides, with three exact
  neighbors when the evidence crosses an ayah boundary. A selected near
  retry needs two independently supported attempts.

The lower modes consider internal ا, و, or ي spelling differences, limited
letter echoes, and single substitutions from the pairs ص/س, ض/ظ, ط/ت, ذ/ز,
ث/ت, ق/ك, and ح/ه. The Quran vocabulary protects different attested words.
A live decoder split such as `ولا` plus a 60 ms `م` can count for `ولم` in
Beginner when exact speech surrounds it. The standalone `ولا` remains a
different word. Segment quality and stable timing still apply. Confirmed
omissions and different words retain the correction gate.

On 34 fixed recognizer-output cases chosen before the wider scoring change,
Beginner went from 27 stops to 2, Intermediate from 28 to 15, and Expert
stayed at 33. The new counts equal 6%, 45%, and 100% of Expert's stops.
A stop means the named word or handoff remained unverified after one reading
or targeted retry. These counts describe controlled fixture behavior.

Tap **Recite** once and follow the current ayah, marked in gray. Words in the
next ayah count when the current one has been verified. Tap **Pause** to release
the microphone, then **Resume** to continue with the same ayah and marks.
**End session** saves the attempt early. The app ends the session when the
passage is complete or when you leave the Recite tab or background the app.

- The live word results are **Correct** in green, **Incorrect** in red,
  and **Missed** in yellow. Tap a flagged word to retry that word by itself,
  then pause briefly. A successful retry turns it green and clears the
  correction. Saved history keeps track of the correction.
- A reliably identified written word stays green when the transcript varies
  in vowels or accent. A stable substitution with a reliable following
  word can show **Incorrect**. Unresolved words receive no result, and
  Hifz keeps them hidden. Pronunciation errors require separate evidence.
- Tap the speaker to hear only the marked word using verified reference
  timings. The microphone stays off during playback. Use **Retry ayah**
  to reread the current ayah if the remaining audio could not be identified.

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

The mobile Recite tab uses the authenticated `/recite/live` WebSocket.
GPU selection also applies to single-ayah uploads. The `/analyze` upload
endpoint uses the original unprompted transcription and whole-phrase
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
- `WS /recite/live` — JWT in the start message and binary 16 kHz mono PCM16
  after `ready`. `feedback` reports word states, and `stop` returns a saved
  `finished` review for attempts with progress. Set `guided` to `true` in
  the start message for guided practice. Wait for `paused` before playing
  reference audio, and for `resumed` before sending PCM again. `resume` can
  include the current `ayah` and a zero-based `word_index` to target a flagged
  word, or `replay_ayah: true` to retry the current ayah. Send `ping` during
  a long pause to keep the same session open.
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

## Android setup from a clean checkout

Install Flutter and the Android toolchain, then check them with `flutter doctor`.
The repository includes the Android launcher icons and manifest. The Flutter
build creates the local SDK settings and supplies the Gradle wrapper from its
tool cache.

```sh
cd mobile
flutter pub get
flutter build apk --debug
```

## Flutter app (`mobile/`)

Complete app covering all 8 report modules:

- **Auth** — login / register (Normal or Hafiz chosen at signup)
- **Home** — greeting, 🔥 streak chip, level + points progress, continue
  reading, Ayah & Hadith of the day
- **Quran** — searchable list of 114 Surahs; Surah view with Verse-by-Verse
  and Reading (continuous Mushaf-style) views, font-size control,
  listen-to-Ayah, save reading position, and a **Hide text (Hifz test)**
  mode that masks Ayahs until tapped
- **Recite** — full passage from the starting ayah, continuous Normal and Hifz
  practice, live word-level corrections, and timed reference audio
- **Progress** — overview stats, mistakes-by-type, accuracy trend,
  badges grid, full session history with detail dialogs
- **Profile** — name, mode, recitation difficulty, notifications, API URL override
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

## Tests

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
