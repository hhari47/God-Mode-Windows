@echo off
cd /d "%~dp0"
echo Starting GodMode for Windows...
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" run.py
) else (
    python run.py
)
if errorlevel 1 pause
