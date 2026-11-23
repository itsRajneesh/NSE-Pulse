@echo off
title NSE Screener - Backend Service (FastAPI)
cd /d "%~dp0backend"
echo Checking port 8055...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8055 ^| findstr LISTENING') do (
    echo Freeing port 8055 from stale PID %%a...
    taskkill /f /t /pid %%a >nul 2>&1
)
echo Starting FastAPI Quantitative Engine on port 8055...
python -m uvicorn app.main:app --host 127.0.0.1 --port 8055 --reload
pause
