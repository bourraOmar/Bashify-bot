@echo off
chcp 65001 >nul
title Bashify Music Downloader Bot
cd /d "%~dp0"

echo ========================================================
echo         Bashify Music Downloader Telegram Bot
echo   Featuring Spotify Search + YouTube & Cloud Fallbacks
echo ========================================================
echo.

if not exist ".\.venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found at .venv
    echo Please run: python -m venv .venv ^& .\.venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

echo [INFO] Cleaning old temporary files from downloads directory...
if not exist "downloads" mkdir "downloads"
del /q "downloads\*.*" 2>nul

echo [INFO] Starting bot...
echo.
".\.venv\Scripts\python.exe" bot.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Bot exited unexpectedly with error code %ERRORLEVEL%.
    pause
) else (
    echo.
    echo [INFO] Bot stopped cleanly.
    pause
)
