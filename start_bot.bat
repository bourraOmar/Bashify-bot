@echo off
title Music Downloader Bot
cd /d "%~dp0"
echo ===========================================
echo   Starting Music Downloader Telegram Bot...
echo   Running locally on residential internet!
echo ===========================================
echo.
".\.venv\Scripts\python.exe" bot.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Bot exited with an error.
    pause
) else (
    pause
)
