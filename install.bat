@echo off
chcp 65001 >nul
title autotrade 安裝程式
cd /d "%~dp0"
echo ============================================
echo  1000X 安裝程式
echo ============================================
echo.
echo [1/3] 檢查 Python 3.11+ ...
python --version >nul 2>&1
if errorlevel 1 (
    echo   錯誤：找不到 Python。
    echo   請至 https://www.python.org 安裝 Python 3.11 或更新版本
    echo   安裝時請勾選「Add Python to PATH」。
    pause
    exit /b 1
)
python -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3, 11) else 1)" >nul 2>&1
if errorlevel 1 (
    echo   錯誤：Python 版本過舊，需要 3.11 或更新版本。
    echo   您目前的版本：
    python --version
    echo   請至 https://www.python.org 升級到 3.11 或更新版本後再執行。
    pause
    exit /b 1
)
echo   完成
echo.
echo [2/3] 建立虛擬環境（.venv）...
if not exist ".venv" (
    python -m venv .venv
)
echo   完成
echo.
echo [3/3] 安裝相依套件（可能需要幾分鐘）...
".venv\Scripts\python.exe" -m pip install -e . --quiet
echo   完成
echo.
echo 完成。啟動 1000X...
".venv\Scripts\python.exe" scripts\run.py
pause
