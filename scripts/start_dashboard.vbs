Set WshShell = CreateObject("WScript.Shell")
projectPath = WScript.Arguments(0)

' 1. Start FastAPI Backend silently
WshShell.Run "cmd.exe /c cd /d """ & projectPath & """ && uv run uvicorn api.main:app --host 0.0.0.0 --port 8000", 0, False

' 2. Start Vite Frontend silently
WshShell.Run "cmd.exe /c cd /d """ & projectPath & "\dashboard"" && npm run dev", 0, False
