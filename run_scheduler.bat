@echo off
chcp 65001 > nul
set PYTHONUTF8=1
set PYTHONPATH=%~dp0
title FA/TA Live Trader Scheduler
uv run python scheduler.py
pause
