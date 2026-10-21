# Quranify — phone testing (local, your PC + your phone)

Same pattern as the GlycoTwin phone tests: **backend runs on your PC,
phone connects over the same Wi-Fi.** Nothing is exposed to the internet.

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
4. In the app: register an account → Quran tab → Surah 112 → Recite on
   any Ayah → record → see the highlighted feedback. Try Continuous
   (Huffaz) mode from the Recite tab too.
   If a connection error appears, open **Profile → Connection**, set the
   API URL to `http://<your LAN IP>:8000`, save, and retry.

### Test journeys worth running
- Register → login persists after app restart
- Surah 1: hide-text (Hifz test) toggle, reading position save, re-open
  app → Home shows "Continue Reading"
- Recite 112:1 correctly → "no mistakes" result; skip a word on purpose
  → that word flagged red; change بِسْمِ's Kasra to Fatha in 1:1 → Harakat flag
- Continuous mode 112:1–3, skip Ayah 2 entirely → "Skipped Ayah: 2"
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
- **Analysis is slow** → CPU inference; the first call also loads the
  model. ~8–14 s per Ayah is normal here.
- **`flutter doctor` Android license errors** → run
  `flutter doctor --android-licenses`.
- **Mic permission** → the app asks on first record; if denied earlier,
  allow it in Android Settings → Apps → Quranify → Permissions.
