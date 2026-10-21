# Quranify — Flutter app

Complete Quranify client (all 8 modules). Backend: `../backend`
(FastAPI). API contract: the backend's `/docs`.

## Run

```bash
flutter pub get
flutter run --dart-define=API_URL=http://10.0.2.2:8000   # Android emulator -> host backend
# Physical phone on the same Wi-Fi: use your PC's LAN IP, or set the
# API URL inside the app (Profile -> Connection).
```

## Verify (matches the VM verification run)

```bash
flutter analyze   # clean
flutter test      # 5 tests: highlight logic, model parsing, login widget
flutter build web --release   # release build proof
flutter build apk --debug     # needs Android SDK + JDK 17 (developer machine)
```

Permissions (Android): microphone (recitation recording) and internet
(API + reference audio) are declared in
`android/app/src/main/AndroidManifest.xml`.
