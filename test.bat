@echo off
cd /d "%~dp0"
echo Running GodMode Test Suite...
".venv\Scripts\python.exe" -m pytest -v
pause
