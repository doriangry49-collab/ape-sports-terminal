@echo off
chcp 65001 >nul
title APE Sports Intelligence Terminal & Telegram Canli Komuta
color 0A

echo ===============================================================================
echo   🏛️  APE SPORTS INTELLIGENCE TERMINAL & CANLI TELEGRAM DAEMON (v2.0)
echo ===============================================================================
echo.

set "PROJECT_ROOT=%~dp0"
cd /d "%PROJECT_ROOT%"
set "PYTHONPATH=%PROJECT_ROOT%\src"

:: [CPU/RAM Throttling] Kisisisel bilgisayari yormamak icin cekirdek sinirlamasi
set "OMP_NUM_THREADS=2"
set "MKL_NUM_THREADS=2"
set "OPENBLAS_NUM_THREADS=2"
set "NUMEXPR_NUM_THREADS=2"

echo [1/3] UI Bundle ve guncel bulten derleniyor...
python ui\build_bundle.py

echo [2/3] FastAPI Yerel Ag Gecidi (http://127.0.0.1:8000/ui/) baslatiliyor...
start "APE FastAPI Server" /min cmd /c "chcp 65001 >nul && set PYTHONPATH=%PROJECT_ROOT%\src && cd /d ""%PROJECT_ROOT%"" && python -m uvicorn api.main:app --app-dir src --host 127.0.0.1 --port 8000"

echo [3/3] Modern Terminal ve Canli Tarama Daemon'i aciliyor...
start "" "%PROJECT_ROOT%\ui\index.html"

echo.
echo ===============================================================================
echo  Canli Tarama Daemon'i devrede:
echo  - Nesine CDN + Pinnacle oranlari 300 saniyede bir (bilgisayari kasmayacak sekilde) taranir.
echo  - +EV degerli firsatlar aninda Telegram'a ve bu terminale aktarilir.
echo  - Kapatmak icin bu pencereyi kapatin veya Ctrl+C yapin.
echo ===============================================================================
echo.
python -u src\live_monitor_daemon.py --interval 300 --ping

echo.
echo [!] Sunucu durdu. Cikmak icin bir tusa basin...
pause >nul
