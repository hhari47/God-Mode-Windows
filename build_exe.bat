@echo off
cd /d "%~dp0"
echo ========================================================
echo Building GodMode Standalone Windows Executable
echo ========================================================
echo.

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" build_desktop.py
) else (
    python build_desktop.py
)

if errorlevel 1 (
    echo.
    echo [ERROR] Build failed. Check errors above.
    pause
    exit /b %errorlevel%
)

echo.
echo [SUCCESS] Build complete! Executable is located in dist\GodMode\GodMode.exe
pause
