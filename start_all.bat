@echo off
title Launch NSE Intraday Screener

if "%1"=="status" goto :STATUS_PAGE

where wt >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo Launching all services in 1 Windows Terminal window with 3 tabs...
    wt -w 0 --title "Control Center" cmd /k "%~dp0start_all.bat" status ; new-tab --title "NSE Backend (FastAPI)" cmd /k "%~dp0run_backend.bat" ; new-tab --title "NSE Frontend (Next.js)" cmd /k "%~dp0run_frontend.bat"
    exit /b
)

echo Windows Terminal (wt.exe) not found, launching in fallback mode...
start "NSE Backend (FastAPI)" cmd /c "%~dp0run_backend.bat"
timeout /t 3 /nobreak >nul
start "NSE Frontend (Next.js)" cmd /c "%~dp0run_frontend.bat"
echo Services starting...
echo Frontend: http://localhost:3055
echo Backend:  http://127.0.0.1:8055
echo Docs:     http://127.0.0.1:8055/docs
timeout /t 3 /nobreak >nul
start http://localhost:3055
pause
exit /b

:STATUS_PAGE
cls
echo ========================================================
echo Launching NSE Automated Intraday Screener & Signal Engine
echo ========================================================
echo.
echo Services running across 3 tabs:
echo  - Tab 1: Control Center & Status
echo  - Tab 2: NSE Backend (FastAPI) [http://127.0.0.1:8055]
echo  - Tab 3: NSE Frontend (Next.js) [http://localhost:3055]
echo.
echo API Documentation: http://127.0.0.1:8055/docs
echo ========================================================
echo Opening browser in 5 seconds...
timeout /t 5 /nobreak >nul
start http://localhost:3055
echo.
echo All services launched! Switch tabs above to view live logs.
echo.
pause
