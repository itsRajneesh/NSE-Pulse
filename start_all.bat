@echo off
title Launch NSE Intraday Screener
echo ========================================================
echo Launching NSE Automated Intraday Screener & Signal Engine
echo ========================================================
start "NSE Backend (FastAPI)" cmd /c "%~dp0run_backend.bat"
timeout /t 3 /nobreak >nul
start "NSE Frontend (Next.js)" cmd /c "%~dp0run_frontend.bat"
echo Services starting...
echo Frontend: http://localhost:3000
echo Backend:  http://127.0.0.1:8000
echo Docs:     http://127.0.0.1:8000/docs
pause
