# Quranify — phone testing (local, your PC + your phone)

Run the backend on your PC and connect the phone over the same Wi-Fi.

## Current Recite workflow

Install the newly built APK, start the backend on your PC, and verify the API URL
in **Profile → Connection** points to the PC's LAN address. Open **Recite**, select
a Surah and starting Ayah, then check:

1. Confirm the selected Arabic passage and round ayah markers. In **Hifz**, the
   markers remain visible and the words are hidden.
2. Tap **Recite** once. Look for the gray current ayah and read in order.
   Matched words should show **Correct** in green while unread words stay
   unmarked. After Al-Fatiha ayahs 1–4, tap **Pause**, then **Resume** and
   continue at ayah 5. Repeat the check with a pause halfway through an ayah.
3. Skip a word and continue far enough for the app to locate the omission.
   Check for **Missed** in yellow. In Hifz, check that recognized words and
   confirmed mistake targets appear while future words stay hidden.
4. Read ahead with a current flag and check that the next ayah receives no
   credit. Tap the flagged word and say it by itself, then pause briefly.
   Try a wrong word and confirm the original mark stays. Say the target
   correctly and check that the original word turns green.
5. Use **End session** in one attempt and finish the passage in another. Confirm a
   single history entry per session with recognized progress.
6. Tap the speaker beside a flagged word during the session. Confirm that
   playback contains only that reference word and earns no word credit.
7. Switch tabs or background the app while listening. Check that capture ends
   and the attempt is saved if the server received recognized progress.
8. Interrupt the backend connection and confirm that the app releases the
   microphone and offers a new attempt.

Restart the PC backend with the current code and wait for **Application
startup complete**. The optimized model and CUDA setup are in `README.md`.
`scripts/smoke_live_stream.py` exercises the live socket using professional
reference audio. Phone microphone behavior and learner pronunciation need
their own checks.

If signup or sign-in cannot reach the server, use **Server connection** on either
screen before logging in. Enter the PC's current Wi-Fi address and press **Test
and save**. This checks the backend before saving. Account and other JSON requests
time out after ten seconds instead of leaving the form stuck. Keep the PC backend
running while using the app.

Run the commands below from the `backend` and `mobile` directories in your checkout.

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
   cd backend
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt      # first time only; torch is a big download
   python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```
   Prepare the optimized model using the README steps. Wait for the
   backend to finish warming up before starting a live session.
2. Find the PC's LAN IP: `ipconfig` → IPv4, e.g. `192.168.1.20`.
   Quick check from the phone browser: `http://192.168.1.20:8000/health`
   should show `{"status":"ok",...}`. If it doesn't load, allow Python
   through Windows Firewall (Private network).
3. **Build/install the app** — connect the phone with USB debugging ON
   (Settings → Developer options), then (terminal 2):
   ```powershell
   cd mobile
   flutter pub get
   flutter run --dart-define=API_URL=http://192.168.1.20:8000
   ```
   Or make an installable APK and copy it to the phone:
   ```powershell
   flutter build apk --debug
   ```
   APK lands at `mobile\build\app\outputs\flutter-apk\app-debug.apk`.
4. In the app, sign in, open **Recite**, select Surah 112, and choose a starting
   ayah and mode. Tap **Recite** and follow the checks above.
   If a connection error appears, open **Profile → Connection**, set the
   API URL to `http://<your LAN IP>:8000`, save, and retry.

### Test journeys worth running
- Register → login persists after app restart
- Surah 1: hide-text (Hifz test) toggle, reading position save, re-open
  app → Home shows "Continue Reading"
- Start at 112:2 and confirm the passage displays ayahs 2–4. Read through
  ayah 3 without touching the phone and check that listening continues.
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
- **Live feedback is slow** → prepare the optimized model and CUDA runtime
  using the README steps. Wait for the app to show **Listening** before reciting.
- **`flutter doctor` Android license errors** → run
  `flutter doctor --android-licenses`.
- **Mic permission** → the app asks on first record; if denied earlier,
  allow it in Android Settings → Apps → Quranify → Permissions.
