@echo off
title APE Sports Intelligence Terminal - Local Gateway
echo ========================================================
echo   APE QUANT SPORTS INTELLIGENCE TERMINAL (v2.0)
echo   FastAPI Gateway + Local Static UI Server
echo ========================================================
echo.
cd /d "%~dp0"
echo [1/3] UI Bundle ve Snapshot guncelleniyor...
python ui\build_bundle.py
echo [2/3] Tarayici sunucu hazir olunca acilacak: http://127.0.0.1:8000/ui/ ...
start /b cmd /c "timeout /t 2 /nobreak >nul & start http://127.0.0.1:8000/ui/"
echo [3/3] FastAPI Sunucusu calistiriliyor (Durdurmak icin pencereyi kapatin veya Ctrl+C)...
set PYTHONPATH=src
python -m uvicorn api.main:app --app-dir src --host 127.0.0.1 --port 8000
