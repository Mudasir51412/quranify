@echo off
title Quranify Backend API Server
echo Starting Quranify Backend API on port 8000...
echo Local health check: http://localhost:8000/health
echo On your phone, use your PC's current Wi-Fi IPv4 address from ipconfig.
echo You can change the address using Server connection before signing in.
echo.
cd /d "%~dp0backend"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
pause
