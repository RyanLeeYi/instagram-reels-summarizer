@echo off
chcp 65001 >nul
title Instagram Reels Summarizer
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -File "start.ps1"
pause
