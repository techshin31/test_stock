@echo off
chcp 65001 > nul
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONPATH=%~dp0
title FA/TA Live Trader Scheduler

where uv > nul 2>&1
if errorlevel 1 (
    echo [ERROR] uv command was not found. Install uv or add it to PATH.
    pause
    exit /b 1
)

where docker > nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker was not found. Start Docker Desktop and try again.
    pause
    exit /b 1
)

echo [INFO] Starting PostgreSQL...
docker compose -f storage\postgres\docker-compose.yml up -d postgres
if errorlevel 1 (
    echo [ERROR] PostgreSQL container could not be started.
    pause
    exit /b 1
)

powershell -NoProfile -Command "$deadline=(Get-Date).AddSeconds(60); while((Get-Date) -lt $deadline) { if((Test-NetConnection -ComputerName localhost -Port 5433 -InformationLevel Quiet -WarningAction SilentlyContinue)) { exit 0 }; Start-Sleep -Seconds 2 }; exit 1"
if errorlevel 1 (
    echo [ERROR] PostgreSQL did not become ready on localhost:5433 within 60 seconds.
    pause
    exit /b 1
)

set "TRADING_MODE=%~1"
if "%TRADING_MODE%"=="" set "TRADING_MODE=--dry-run"
echo [INFO] Scheduler mode: %TRADING_MODE%
uv run python scheduler.py %TRADING_MODE%
if errorlevel 1 echo [ERROR] Scheduler exited unexpectedly. Check logs\scheduler.log and logs\live_trader.log.
pause
