@echo off
title NSE Screener - Frontend (Next.js)
cd /d "%~dp0frontend"
echo Checking port 3055...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :3055 ^| findstr LISTENING') do (
    echo Freeing port 3055 from stale PID %%a...
    taskkill /f /t /pid %%a >nul 2>&1
)
if exist ".next" rmdir /s /q ".next"
echo Starting Next.js Web App on http://localhost:3055...
npm run dev
pause
