@echo off
cd /d "%~dp0"
echo Starting GodMode for Windows...

:: Terminate any stale background instances (Python or Karna) to ensure clean hotkey registration
powershell -NoProfile -Command "Get-Process python, pythonw, Karna.Presentation -ErrorAction SilentlyContinue | Where-Object { $_.Id -ne $PID } | Stop-Process -Force -ErrorAction SilentlyContinue" >nul 2>&1

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" run.py
) else (
    python run.py
)
if errorlevel 1 pause
