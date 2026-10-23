@echo off
title Quranify USB APK Installer
echo Installing Quranify to connected Android phone via ADB...
echo.
set "QURANIFY_ADB=adb"
if exist "%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe" set "QURANIFY_ADB=%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"
set "QURANIFY_APK=%~dp0dist\quranify-practice.apk"
if not exist "%QURANIFY_APK%" set "QURANIFY_APK=%~dp0mobile\build\app\outputs\flutter-apk\app-debug.apk"
if not exist "%QURANIFY_APK%" (
    echo Build the APK first: cd mobile then flutter build apk --debug
    pause
    exit /b 1
)
"%QURANIFY_ADB%" install -r "%QURANIFY_APK%"
if errorlevel 1 (
    echo Installation failed. Check ADB and USB debugging.
    pause
    exit /b 1
)
echo.
pause
