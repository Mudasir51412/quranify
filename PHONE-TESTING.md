# Quranify — phone testing (local, your PC + your phone)

Same pattern as the GlycoTwin phone tests: **backend runs on your PC,
phone connects over the same Wi-Fi.** Nothing is exposed to the internet.

## Current Recite workflow

Install the newly built APK, start the backend on your PC, and verify the API URL
in **Profile → Connection** points to the PC's LAN address. Open **Recite**, select
a Surah and starting Ayah, then check:

1. Arabic ayahs are visible before you start. **Hifz · Hide text** hides every word.
2. Press **Recite beside one Ayah**. Only its button becomes **Pause**; other
   recording buttons and the Surah/Ayah selectors are disabled.
3. Read that whole Ayah, then press **Pause**. Only now should **Analyzing this
   ayah…** appear. Feedback belongs beneath the selected Ayah, without auto-advance.
4. Skip a word deliberately, then submit. A confirmed **Missed** word should be
   faint; confirmed **Wrong** words should receive a light red highlight. In Hifz
   only those reference words are revealed after analysis.
5. Press **Try again** on that Ayah. Its previous hints clear for a fresh recording,
   while other Ayahs keep their feedback.
6. Switch tabs or background the app during recording. The microphone should
   stop and the unfinished clip should be cancelled without upload.
7. Stop the backend, record and submit, and check that a readable error appears
   with recording controls enabled again. Analysis times out after two minutes.
8. Stretch words naturally, repeat a word, and restart a phrase. These should
   not create duplicate-word penalties. If recognition is unreliable, the app
   asks you to retry a short phrase without labeling a word "unclear" or penalizing it.
9. Tap **Listen** below a problem phrase. Only the displayed phrase should play.
   Then tap **Try this phrase**, read that phrase, and press **Pause**. A successful
   retry clears its own highlights; errors elsewhere remain. A failed recording
   or an unconfirmed retry must not erase existing feedback.
10. Start a recording while Listen is still loading, or background the app.
    Reference playback must not start later over the microphone.

The practice-feedback build is `dist/quranify-practice.apk`. Restart the PC
backend to load the updated analysis and timing endpoints before using it.
Wait for **Application startup complete** after the model warmup message.
The first recording should then use the already loaded model. A healthy warmed
GPU backend reports `inference.status=ready` and `inference.device=cuda` at `/health`.
`scripts/smoke_practice_feedback.py` checks the GPU model using professional
reference audio, a synthetic tempo change/restart, and a timed phrase clip.
These checks do not establish accuracy for your voice or physical-phone playback.

The optimized model and CUDA setup are documented in `README.md`. Inference runs
on the PC backend. The per-Ayah APK was installed on the Infinix X6850 over USB.
Microphone startup, disabled neighboring controls, and cancellation on leaving
the tab were checked on that phone without uploading a test session. Real WAV
uploads with cached professional reference audio passed through the GPU model in
an isolated database. Feedback accuracy for actual learner speech still needs
the phone rehearsal above.

If signup or sign-in cannot reach the server, use **Server connection** on either
screen before logging in. Enter the PC's current Wi-Fi address and press **Test
and save**. This checks the backend before saving. Account and other JSON requests
time out after ten seconds instead of leaving the form stuck. Keep the PC backend
running while using the app.

You need the project folder (`quranify-mvp`) on your PC — unzip the
bundle Muse prepared.

---

## Path A — the real app on your phone (full test, incl. recording)

### One-time setup on the PC
1. Install **Android Studio** (it brings the Android SDK + JDK 17).
   Open it once → SDK Manager → install "Android SDK Platform 35" (or 36)
   and "Android SDK Build-Tools".
2. Install the **Flutter SDK** (flutter.dev → Windows zip), unzip e.g. to
   `C:\flutter`, add `C:\flutter\bin` to PATH.
3. In a terminal: `flutter doctor` → fix anything it flags, run
   `flutter doctor --android-licenses` and accept.
4. Install **ffmpeg** (needed by the backend to read audio):
   `winget install Gyan.FFmpeg` — or download from ffmpeg.org.
5. Python 3.11 or 3.12 installed.

### Every test session
1. **Start the backend** (terminal 1):
   ```powershell
   cd quranify-mvp\backend
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt      # first time only; torch is a big download
   python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```
   First ever `/analyze` call downloads the Whisper model (~460 MB) once.
   On a CPU each analysis takes roughly 8–14 seconds — that is expected
   on this setup (the VM benchmark measured the same).
2. Find the PC's LAN IP: `ipconfig` → IPv4, e.g. `192.168.1.20`.
   Quick check from the phone browser: `http://192.168.1.20:8000/health`
   should show `{"status":"ok",...}`. If it doesn't load, allow Python
   through Windows Firewall (Private network).
3. **Build/install the app** — connect the phone with USB debugging ON
   (Settings → Developer options), then (terminal 2):
   ```powershell
   cd quranify-mvp\mobile
   flutter pub get
   flutter run --dart-define=API_URL=http://192.168.1.20:8000
   ```
   Or make an installable APK and copy it to the phone:
   ```powershell
   flutter build apk --debug
   ```
   APK lands at `mobile\build\app\outputs\flutter-apk\app-debug.apk`.
4. In the app: register an account → Recite tab → Surah 112 → choose a
   starting Ayah → optionally hide text with Hifz → press Recite beside an Ayah.
   Read that Ayah and press Pause. Feedback appears after backend analysis.
   If a connection error appears, open **Profile → Connection**, set the
   API URL to `http://<your LAN IP>:8000`, save, and retry.

### Test journeys worth running
- Register → login persists after app restart
- Surah 1: hide-text (Hifz test) toggle, reading position save, re-open
  app → Home shows "Continue Reading"
- Recite 112:1 correctly and submit with Pause, then Try again with a deliberate
  omission → a faint skipped-word hint appears after analysis.
- Start at 112:2; only Ayahs 2–4 should be displayed. Practice Ayah 3 and confirm
  feedback appears only there. Finish the selected Ayah before pressing Pause.
- Progress tab: accuracy, streak, badges update after sessions

---

## Path B — quick look only (no Android toolchain)

The web build is already compiled in the bundle (`mobile/build/web`).

```powershell
cd quranify-mvp\mobile\build\web
python -m http.server 8080
```
Phone browser → `http://<LAN IP>:8080`. Browsing, login, Quran and
dashboard work (backend from Path A step 1 must be running, and the API
URL inside the web app defaults to `localhost:8000` — so for Path B also
open the site once on the PC and set Profile → Connection to the LAN IP…
simpler: use Path B only to look at the UI on the PC itself at
`http://localhost:8080`).

⚠️ **Recording will not work in the phone browser**: Chrome blocks the
microphone on plain-HTTP LAN pages. Recitation testing needs Path A
(the installed app) — or the PC browser at localhost.

---

## Troubleshooting
- **Phone can't reach the backend** → same Wi-Fi? firewall? correct LAN
  IP (not 127.0.0.1)? `/health` check first.
- **Analysis is slow** → prepare the optimized model and CUDA runtime using
  the README steps. The first submission may load the model; feedback begins
  only after Pause. The microphone is already stopped while analysis runs.
- **`flutter doctor` Android license errors** → run
  `flutter doctor --android-licenses`.
- **Mic permission** → the app asks on first record; if denied earlier,
  allow it in Android Settings → Apps → Quranify → Permissions.
