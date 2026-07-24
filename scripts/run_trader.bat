@echo off
setlocal
cd /d "%~dp0.."
set "PROJECT_ROOT=%cd%"
set "PYTHONPATH=%cd%"
set PYTHONUTF8=1
if not defined MAX_DAILY_LOSS_RATE set "MAX_DAILY_LOSS_RATE=0.03"
if not defined TRADING_KILL_SWITCH set "TRADING_KILL_SWITCH=false"
if not defined REAL_PROMOTION_SNAPSHOT set "REAL_PROMOTION_SNAPSHOT=reports\promotion\real_readiness.json"

where uv > nul 2>&1
if not errorlevel 1 goto :uv_ready
echo [ERROR] uv command was not found. Install uv or add it to PATH.
pause
exit /b 1

:uv_ready
echo ========================================================
echo   FA/TA Automated Trading - Manual Runner
echo ========================================================
echo   Daily loss limit: %MAX_DAILY_LOSS_RATE%
echo   Entry kill switch: %TRADING_KILL_SWITCH%
echo.
echo 1. Premarket preparation - DRY_RUN, no orders
echo 2. One intraday DRY_RUN - candidates only
echo 3. One PAPER run - gated mock-account orders
echo 4. One REAL run - gated and manually confirmed
echo 5. Liquidate REAL positions
echo 6. Liquidate PAPER positions
echo 7. Capture and certify PAPER baseline - no orders
echo.
set "choice="
set /p choice="Select mode - 1/2/3/4/5/6/7: "
if "%choice%"=="1" goto :premarket
if "%choice%"=="2" goto :dry_run
if "%choice%"=="3" goto :paper
if "%choice%"=="4" goto :real
if "%choice%"=="5" goto :liquidate_real
if "%choice%"=="6" goto :liquidate_paper
if "%choice%"=="7" goto :paper_baseline
echo Invalid selection. Exiting.
goto :finish

:premarket
echo.
echo [PREMARKET DRY_RUN] Calculating FA candidates only.
uv run python run_live_trader.py --mock --dry-run --premarket
goto :finish

:dry_run
echo.
echo [DRY_RUN] Calculating intraday signals and order candidates only.
uv run python run_live_trader.py --mock --dry-run
goto :finish

:paper
call :check_paper_gate
if errorlevel 1 goto :finish
call :check_paper_baseline
if errorlevel 1 goto :finish
echo.
echo [PAPER] Gate passed. Submitting mock-account orders.
uv run python run_live_trader.py --mock
goto :finish

:real
call :check_real_gate
if errorlevel 1 goto :finish
set "LIVE_CONFIRM="
set /p LIVE_CONFIRM="Type LIVE to enable real-account orders: "
if /I "%LIVE_CONFIRM%"=="LIVE" goto :real_confirmed
echo [CANCELLED] Real-account run was cancelled.
goto :finish

:real_confirmed
echo.
call :ensure_real_baseline
if errorlevel 1 goto :finish
echo [REAL] Submitting real-account orders.
uv run python run_live_trader.py --live
goto :finish

:liquidate_real
set "LIQUIDATE_CONFIRM="
set /p LIQUIDATE_CONFIRM="Type LIQUIDATE to sell all REAL positions: "
if /I "%LIQUIDATE_CONFIRM%"=="LIQUIDATE" goto :liquidate_real_confirmed
echo [CANCELLED] Real-account liquidation was cancelled.
goto :finish

:liquidate_real_confirmed
uv run python run_live_trader.py --live --liquidate --confirm-liquidate LIQUIDATE
goto :finish

:liquidate_paper
set "LIQUIDATE_CONFIRM="
set /p LIQUIDATE_CONFIRM="Type LIQUIDATE to sell all PAPER positions: "
if /I "%LIQUIDATE_CONFIRM%"=="LIQUIDATE" goto :liquidate_paper_confirmed
echo [CANCELLED] Paper-account liquidation was cancelled.
goto :finish

:liquidate_paper_confirmed
uv run python run_live_trader.py --mock --liquidate --confirm-liquidate LIQUIDATE
goto :finish

:paper_baseline
call :check_paper_gate
if errorlevel 1 goto :finish
echo.
echo [PAPER BASELINE] Reading the mock account only. No order will be sent.
uv run python run_live_trader.py --mock --snapshot-only
if errorlevel 1 (
    echo [ERROR] Account snapshot failed. Baseline was not created.
    goto :finish
)
uv run python -m core.analytics.trading_performance --mode PAPER --initialize-baseline --confirm-baseline CLEAN_PAPER_BASELINE
if errorlevel 1 (
    echo [ERROR] Baseline certification failed. Existing baselines are never overwritten automatically.
    goto :finish
)
echo [OK] PAPER baseline certified. PAPER execution remains a separate manual action.
goto :finish

:check_paper_gate
echo [INFO] Checking DRY_RUN to PAPER promotion gate...
uv run python -m core.analytics.trading_kpis --target PAPER --operational-log logs\dry_run\operational_health.jsonl --readiness-json reports\promotion\dry_run\latest.json
if errorlevel 1 goto :paper_blocked
exit /b 0

:paper_blocked
echo [BLOCKED] PAPER gate failed. Keep running DRY_RUN.
exit /b 1

:check_paper_baseline
echo [INFO] Checking the certified PAPER performance baseline...
uv run python -m core.analytics.trading_performance --mode PAPER --check-baseline
if errorlevel 1 goto :paper_baseline_missing
uv run python run_live_trader.py --mock --snapshot-only
if errorlevel 1 goto :paper_account_mismatch
uv run python -m core.analytics.trading_performance --mode PAPER --check-baseline --check-latest-snapshot
if errorlevel 1 goto :paper_account_mismatch
exit /b 0

:paper_baseline_missing
echo [BLOCKED] PAPER baseline is missing. Run option 7 before PAPER trading.
exit /b 1

:paper_account_mismatch
echo [BLOCKED] Current PAPER account could not be verified against the baseline.
exit /b 1

:ensure_real_baseline
uv run python -m core.analytics.trading_performance --mode REAL --check-baseline > nul 2>&1
if not errorlevel 1 goto :verify_real_baseline
echo [REAL BASELINE] Reading the real account only. No order will be sent.
uv run python run_live_trader.py --live --snapshot-only
if errorlevel 1 goto :real_baseline_failed
uv run python -m core.analytics.trading_performance --mode REAL --initialize-baseline --confirm-baseline CLEAN_REAL_BASELINE
if errorlevel 1 goto :real_baseline_failed
echo [OK] REAL baseline certified before the first real order.
exit /b 0

:verify_real_baseline
echo [REAL BASELINE] Verifying the current real account. No order will be sent.
uv run python run_live_trader.py --live --snapshot-only
if errorlevel 1 goto :real_baseline_failed
uv run python -m core.analytics.trading_performance --mode REAL --check-baseline --check-latest-snapshot
if errorlevel 1 goto :real_baseline_failed
exit /b 0

:real_baseline_failed
echo [BLOCKED] REAL baseline certification failed. No real-account order was sent.
exit /b 1

:check_real_gate
echo [INFO] Checking PAPER to REAL promotion gate...
uv run python -m core.analytics.trading_kpis --target REAL --operational-log logs\paper\operational_health.jsonl --performance-json "%REAL_PROMOTION_SNAPSHOT%"
if errorlevel 1 goto :real_blocked
exit /b 0

:real_blocked
echo [BLOCKED] REAL gate failed. No real-account order was sent.
exit /b 1

:finish
echo.
pause
