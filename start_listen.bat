@echo off
chcp 65001 >nul
title autotrade listener
cd /d "%~dp0"
echo Starting listener...
echo To stop: just close this window
".venv\Scripts\python.exe" scripts\listen.py
pause
