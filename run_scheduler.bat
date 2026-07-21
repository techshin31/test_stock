@echo off
setlocal EnableDelayedExpansion
chcp 65001 > nul
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONPATH=%~dp0
if not defined MAX_DAILY_LOSS_RATE set "MAX_DAILY_LOSS_RATE=0.03"
if not defined TRADING_KILL_SWITCH set "TRADING_KILL_SWITCH=false"
if not defined REAL_PROMOTION_SNAPSHOT set "REAL_PROMOTION_SNAPSHOT=reports\promotion\real_readiness.json"
if not defined SCHEDULER_PAUSE_ON_EXIT set "SCHEDULER_PAUSE_ON_EXIT=false"
title FA/TA Live Trader Scheduler

where uv > nul 2>&1
if errorlevel 1 (
    echo [ERROR] uv command was not found. Install uv or add it to PATH.
    if /I "%SCHEDULER_PAUSE_ON_EXIT%"=="true" pause
    exit /b 1
)

where docker > nul 2>&1
if errorlevel 1 (
    echo [ERROR] Docker was not found. Start Docker Desktop and try again.
    if /I "%SCHEDULER_PAUSE_ON_EXIT%"=="true" pause
    exit /b 1
)

echo [INFO] Starting PostgreSQL...
docker compose -f storage\postgres\docker-compose.yml up -d postgres
if errorlevel 1 (
    echo [ERROR] PostgreSQL container could not be started.
    if /I "%SCHEDULER_PAUSE_ON_EXIT%"=="true" pause
    exit /b 1
)

powershell -NoProfile -Command "$deadline=(Get-Date).AddSeconds(60); while((Get-Date) -lt $deadline) { if((Test-NetConnection -ComputerName localhost -Port 5433 -InformationLevel Quiet -WarningAction SilentlyContinue)) { exit 0 }; Start-Sleep -Seconds 2 }; exit 1"
if errorlevel 1 (
    echo [ERROR] PostgreSQL did not become ready on localhost:5433 within 60 seconds.
    if /I "%SCHEDULER_PAUSE_ON_EXIT%"=="true" pause
    exit /b 1
)

echo [INFO] Applying database migrations...
uv run python -m storage.postgres.migrate
if errorlevel 1 (
    echo [ERROR] Database migration failed. Scheduler was not started.
    if /I "%SCHEDULER_PAUSE_ON_EXIT%"=="true" pause
    exit /b 1
)

set "TRADING_MODE=%~1"
if "%TRADING_MODE%"=="" set "TRADING_MODE=--paper"
if /I "%TRADING_MODE%"=="--paper" (
    echo [INFO] Checking DRY_RUN to PAPER promotion gate...
    uv run python -m core.analytics.trading_kpis --target PAPER --operational-log logs\dry_run\operational_health.jsonl --readiness-json reports\promotion\dry_run\latest.json
    if errorlevel 1 (
        echo [BLOCKED] PAPER promotion gate did not pass. Keep using --dry-run.
        if /I "%SCHEDULER_PAUSE_ON_EXIT%"=="true" pause
        exit /b 1
    )
    echo [INFO] Checking the certified PAPER performance baseline...
    uv run python -m core.analytics.trading_performance --mode PAPER --check-baseline
    if errorlevel 1 (
        echo [BLOCKED] PAPER baseline is missing. Use run_trader.bat option 7 first.
        if /I "%SCHEDULER_PAUSE_ON_EXIT%"=="true" pause
        exit /b 1
    )
    echo [INFO] Verifying the current mock account against the certified baseline...
    uv run python run_live_trader.py --mock --snapshot-only
    if errorlevel 1 (
        echo [BLOCKED] Current PAPER account could not be read. No order was sent.
        if /I "%SCHEDULER_PAUSE_ON_EXIT%"=="true" pause
        exit /b 1
    )
    uv run python -m core.analytics.trading_performance --mode PAPER --check-baseline --check-latest-snapshot
    if errorlevel 1 (
        echo [BLOCKED] Current PAPER account does not match the certified baseline.
        if /I "%SCHEDULER_PAUSE_ON_EXIT%"=="true" pause
        exit /b 1
    )
)
if /I "%TRADING_MODE%"=="--live" (
    echo [INFO] Checking PAPER to REAL promotion gate...
    uv run python -m core.analytics.trading_kpis --target REAL --operational-log logs\paper\operational_health.jsonl --performance-json "%REAL_PROMOTION_SNAPSHOT%"
    if errorlevel 1 (
        echo [BLOCKED] REAL promotion gate did not pass. Live trading will not start.
        if /I "%SCHEDULER_PAUSE_ON_EXIT%"=="true" pause
        exit /b 1
    )
    set "LIVE_CONFIRM="
    set /p LIVE_CONFIRM="Type LIVE to enable the real-account scheduler: "
    if /I not "!LIVE_CONFIRM!"=="LIVE" (
        echo [CANCELLED] Real-account scheduler was not started.
        if /I "%SCHEDULER_PAUSE_ON_EXIT%"=="true" pause
        exit /b 1
    )
    uv run python -m core.analytics.trading_performance --mode REAL --check-baseline > nul 2>&1
    if errorlevel 1 (
        echo [REAL BASELINE] Reading the real account only. No order will be sent.
        uv run python run_live_trader.py --live --snapshot-only
        if errorlevel 1 (
            echo [BLOCKED] Real-account snapshot failed. No order was sent.
            if /I "%SCHEDULER_PAUSE_ON_EXIT%"=="true" pause
            exit /b 1
        )
        uv run python -m core.analytics.trading_performance --mode REAL --initialize-baseline --confirm-baseline CLEAN_REAL_BASELINE
        if errorlevel 1 (
            echo [BLOCKED] REAL baseline certification failed. No order was sent.
            if /I "%SCHEDULER_PAUSE_ON_EXIT%"=="true" pause
            exit /b 1
        )
    ) else (
        echo [REAL BASELINE] Verifying the current real account. No order will be sent.
        uv run python run_live_trader.py --live --snapshot-only
        if errorlevel 1 (
            echo [BLOCKED] Current real account could not be read. No order was sent.
            if /I "%SCHEDULER_PAUSE_ON_EXIT%"=="true" pause
            exit /b 1
        )
        uv run python -m core.analytics.trading_performance --mode REAL --check-baseline --check-latest-snapshot
        if errorlevel 1 (
            echo [BLOCKED] Current real account does not match the certified baseline.
            if /I "%SCHEDULER_PAUSE_ON_EXIT%"=="true" pause
            exit /b 1
        )
    )
)
echo [INFO] Scheduler mode: %TRADING_MODE%
echo [INFO] Daily loss limit: %MAX_DAILY_LOSS_RATE% / Entry kill switch: %TRADING_KILL_SWITCH%
uv run python scheduler.py %TRADING_MODE%
set "SCHEDULER_EXIT_CODE=%ERRORLEVEL%"
if not "%SCHEDULER_EXIT_CODE%"=="0" echo [ERROR] Scheduler exited unexpectedly. Check logs\scheduler.log and logs\live_trader.log.
if /I "%SCHEDULER_PAUSE_ON_EXIT%"=="true" pause
exit /b %SCHEDULER_EXIT_CODE%
