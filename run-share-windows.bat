@echo off
rem Double-click me on Windows: starts the app AND a public link (ngrok) with a QR code for friends.
title Remind Me Bro - Run ^& Share
cd /d "%~dp0"
set RMB_SHARE=1
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run.ps1" %*
if errorlevel 1 pause
