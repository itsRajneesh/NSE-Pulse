@echo off
title NSE Screener - Backend Service (FastAPI)
cd /d "%~dp0backend"
echo Starting FastAPI Quantitative Engine on port 8000...
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
pause
