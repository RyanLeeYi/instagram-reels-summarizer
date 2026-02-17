@echo off
chcp 65001 >nul 2>&1
REM ========================================
REM  Start Chrome CDP (Chrome DevTools Protocol)
REM  For NotebookLM automation
REM ========================================
REM  Uses your default Chrome profile (already logged in to Google).
REM  NOTE: Close all other Chrome windows before running this script,
REM        because Chrome only allows one instance per profile.

set CDP_PORT=9222
set CHROME_PROFILE=%USERPROFILE%\.chrome-cdp-notebooklm

set "CHROME_PATH="

if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" (
    set "CHROME_PATH=C:\Program Files\Google\Chrome\Application\chrome.exe"
)
if not defined CHROME_PATH if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" (
    set "CHROME_PATH=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
)
if not defined CHROME_PATH if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" (
    set "CHROME_PATH=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
)

if not defined CHROME_PATH (
    echo [ERROR] Chrome not found. Please set CHROME_PATH manually.
    pause
    exit /b 1
)

echo ========================================
echo  Chrome CDP starting...
echo  Port: %CDP_PORT%
echo  Profile: Default Chrome profile
echo  Chrome: %CHROME_PATH%
echo ========================================
echo.
echo  Using your default Chrome profile (Google already logged in).
echo  Do NOT close Chrome while the bot is running.
echo ========================================

start "" "%CHROME_PATH%" --remote-debugging-port=%CDP_PORT% --user-data-dir="%CHROME_PROFILE%" --no-first-run --no-default-browser-check https://notebooklm.google.com
