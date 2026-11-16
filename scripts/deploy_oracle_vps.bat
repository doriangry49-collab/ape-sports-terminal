@echo off
chcp 65001 >nul
title APE Sports-Engine - Oracle Cloud VPS Deployment Helper
color 0B

echo ===============================================================================
echo   ☁️  APE SPORTS-ENGINE ORACLE CLOUD VPS DEPLOYMENT HELPER
echo ===============================================================================
echo.

set "PEM_KEY=C:\Users\Thea-Aria\.ssh\oracle-key"
set "VPS_USER=ubuntu"
set "VPS_IP=158.101.160.116"

if not exist "%PEM_KEY%" (
    echo [HATA] SSH anahtari bulunamadi: %PEM_KEY%
    pause
    exit /b 1
)

echo [1/3] Oracle VPS Baglantisi Test Ediliyor (%VPS_IP%)...
ssh -i "%PEM_KEY%" -o ConnectTimeout=5 -o StrictHostKeyChecking=no %VPS_USER%@%VPS_IP% "echo '[OK] Sunucuya basariyla baglanildi. Uptime:' && uptime"

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [UYARI] Sunucuya dogrudan baglanilamadi. IP veya Guvenlik Duvari (Security List) kontrol edilmeli.
    echo.
    pause
    exit /b 1
)

echo.
echo [2/3] Sunucuda Python3 ve Gerekli Paketlerin Durumu:
ssh -i "%PEM_KEY%" %VPS_USER%@%VPS_IP% "python3 --version 2>/dev/null || echo 'Python3 kurulu degil'"

echo.
echo ===============================================================================
echo  Bulut Sunucuda 7/24 Arka Plan Calistirma Komutu (tmux / nohup):
echo.
echo    ssh -i "%PEM_KEY%" %VPS_USER%@%VPS_IP%
echo    tmux new -s ape_daemon
echo    python3 sports-engine/src/live_monitor_daemon.py --interval 180
echo.
echo  (tmux'tan cikmak icin Ctrl+B ardindan D tusuna basin. Surec arkada 7/24 calisir)
echo ===============================================================================
echo.
pause
