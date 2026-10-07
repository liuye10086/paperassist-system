@echo off
setlocal
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0dev\dev.ps1" %*
exit /b %errorlevel%
