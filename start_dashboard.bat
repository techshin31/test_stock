@echo off
cd /d "%~dp0"
start "FastAPI Backend" cmd /c "uv run uvicorn api.main:app --host 0.0.0.0 --port 8000"
cd dashboard
start "Vite Frontend" cmd /c "npm run dev"
exit
