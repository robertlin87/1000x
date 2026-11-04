@echo off
chcp 65001 >nul
title autotrade runner
cd /d "%~dp0"
echo Starting auto-trade runner...
echo *** This WILL place REAL orders (trial: min qty per signal) ***
echo To stop: just close this window
".venv\Scripts\python.exe" scripts\run.py
pause
