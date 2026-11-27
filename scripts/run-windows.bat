@echo off
rem Double-click me on Windows: installs what is missing, starts the app and opens the browser.
rem Same as run-share-windows.bat in the main folder, without the public link.
title Remind Me Bro - Run ^& Go
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" %*
if errorlevel 1 pause
