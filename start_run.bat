@echo off
chcp 65001 >nul
title autotrade 執行器
cd /d "%~dp0"
echo 啟動自動跟單執行器...
echo *** 這將會下「真實」訂單 ***
echo 停止方式：直接關閉此視窗
".venv\Scripts\python.exe" scripts\run.py
pause
