@echo off
cd /d "%~dp0"
echo Starting GodMode for Windows...

:: Terminate any stale background GodMode python instances to ensure clean hotkey registration
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { ($_.CommandLine -like '*run.py*' -or $_.CommandLine -like '*godmode*') -and $_.ProcessId -ne $PID } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" run.py
) else (
    python run.py
)
if errorlevel 1 pause
