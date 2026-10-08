@echo off
setlocal
set PAPERASSIST_RUN_QUEUE_TESTS=1
cd /d "%~dp0..\backend"
".venv\Scripts\python.exe" -m pytest tests/queue -q -s %*
exit /b %errorlevel%
