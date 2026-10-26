@echo off
cd /d "%~dp0"
echo Running GodMode Test Suite...
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m pytest -v
) else (
    python -m pytest -v
)
pause
