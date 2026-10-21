# Copy-paste prompt for your PC agent — Quranify phone-test bring-up

> You are helping bring up the Quranify project (unzipped as
> `quranify-mvp`) on this PC for phone testing. Follow these steps
> exactly and report at the end.
>
> HARD RULES:
> - No git operations of any kind.
> - Do not edit any .env file, secret, or credential.
> - No recursive deletes. No package upgrades beyond the installs named
>   below. If a step needs something not listed here, STOP and report
>   instead of improvising.
>
> STEPS:
> 1. Check prerequisites and report which exist: `flutter --version`,
>    `python --version`, `ffmpeg -version`. If Flutter is missing, STOP
>    and report (installing Android Studio/Flutter is a manual step).
> 2. Backend: in `quranify-mvp\backend`, create `.venv` if absent,
>    activate it, `pip install -r requirements.txt`, then start:
>    `python -m uvicorn app.main:app --host 0.0.0.0 --port 8000`
>    (leave it running). Verify `http://localhost:8000/health` returns
>    status ok.
> 3. Report this PC's LAN IPv4 address (from `ipconfig`).
> 4. App: in `quranify-mvp\mobile`, run `flutter pub get`, then build:
>    `flutter build apk --debug`. Report the APK path
>    (`build\app\outputs\flutter-apk\app-debug.apk`) and its size.
> 5. Final report: backend health result, LAN IP, APK path — and
>    anything that failed, verbatim.
