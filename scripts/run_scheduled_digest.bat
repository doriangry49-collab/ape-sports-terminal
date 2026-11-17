@echo off
setlocal
cd /d "%~dp0\.."

echo [%DATE% %TIME%] Starting APE Sports-Engine daily digest cycle...
python scripts\run_daily_prototype.py --no-ui-sync
if errorlevel 1 (
    echo [WARN] run_daily_prototype.py exited with non-zero code %ERRORLEVEL%
)

python ui\build_bundle.py
if errorlevel 1 (
    echo [ERROR] ui\build_bundle.py failed with code %ERRORLEVEL%
    exit /b %ERRORLEVEL%
)

if /i "%APE_ENABLE_TELEGRAM_SIGNALS%"=="1" (
    python scripts\send_daily_telegram_digest.py --enable-send
    if errorlevel 1 (
        echo [WARN] send_daily_telegram_digest.py failed with code %ERRORLEVEL%
    )
) else (
    echo [PASSIVE MODE] Telegram signal dispatch is disabled.
)

echo [%DATE% %TIME%] Cycle completed.
endlocal
