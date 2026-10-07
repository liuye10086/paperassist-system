@echo off
setlocal
"%~dp0..\backend\.venv\Scripts\python.exe" "%~dp0setup_database_roles.py"
set "EXIT_CODE=%ERRORLEVEL%"
echo.
pause
exit /b %EXIT_CODE%