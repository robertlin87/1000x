@echo off
chcp 65001 >nul
title autotrade installer
cd /d "%~dp0"
echo ============================================
echo  AutoTrade Installer
echo ============================================
echo.
echo [1/3] Checking Python 3.11+ ...
python --version >nul 2>&1
if errorlevel 1 (
    echo   ERROR: Python not found.
    echo   Please install Python 3.11 or newer from https://www.python.org
    echo   Remember to check "Add Python to PATH" during install.
    pause
    exit /b 1
)
echo   OK
echo.
echo [2/3] Creating virtual environment (.venv) ...
if not exist ".venv" (
    python -m venv .venv
)
echo   OK
echo.
echo [3/3] Installing dependencies (may take a few minutes) ...
".venv\Scripts\python.exe" -m pip install -e . --quiet
echo   OK
echo.
echo Done. Starting AutoTrade...
".venv\Scripts\python.exe" run_app.py
pause
