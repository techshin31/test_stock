Set WshShell = CreateObject("WScript.Shell")
projectPath = "C:\dev\project\Service_Stock_Analysis"
WshShell.Run "cmd.exe /c set PATH=%PATH%;C:\Users\Playdata\.local\bin;C:\Users\Playdata\AppData\Roaming\uv\python\cpython-3.10-windows-x86_64-none && cd /d """ & projectPath & """ && """ & projectPath & "\scripts\run_scheduler.bat"" --paper", 0, False
