@echo off
chcp 65001
echo ========================================================
echo   FA/TA 모멘텀 자동매매 봇 (수동 실행용)
echo ========================================================
echo.
echo 1. 장 시작 전 준비 스크립트 실행 (08:30 전용)
echo 2. 장중 모의 매매 1회 실행 (테스트용)
echo 3. 장중 실전 매매 1회 실행 (실전 계좌)
echo.
set /p choice="원하는 모드를 선택하세요 (1/2/3): "

set PYTHONPATH=c:\dev\project\Service_Stock_Analysis
set PYTHONUTF8=1

if "%choice%"=="1" (
    echo.
    echo [프리마켓 준비 중...] 오늘의 FA 우량주 후보를 필터링합니다.
    uv run python run_live_trader.py --premarket
) else if "%choice%"=="2" (
    echo.
    echo [모의 매매 실행 중...] 장중 주가(TA)를 확인하고 모의로 매매합니다.
    uv run python run_live_trader.py --mock
) else if "%choice%"=="3" (
    echo.
    echo [실전 매매 실행 중...] 장중 주가(TA)를 확인하고 즉시 매매합니다. (실제 계좌 연동 주의!)
    uv run python run_live_trader.py
) else (
    echo 잘못된 입력입니다. 종료합니다.
)

echo.
pause
