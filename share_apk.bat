@echo off
title Quranify APK Download Portal
echo Starting Quranify APK Download Portal on port 8080...
echo On your phone, open http://YOUR-PC-WIFI-IP:8080 using the IPv4 from ipconfig.
echo Place the built APK in dist before starting this portal.
echo.
if not exist "%~dp0dist\*.apk" (
    echo No APK found in dist. Build it first and copy it into dist.
    pause
    exit /b 1
)
cd /d "%~dp0dist"
..\backend\.venv\Scripts\python.exe -m http.server 8080 --bind 0.0.0.0
pause
