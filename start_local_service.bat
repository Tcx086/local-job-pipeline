@echo off
setlocal

set "SCRIPT=%~dp0start_local_service.ps1"

if not exist "%SCRIPT%" (
    echo Could not find start_local_service.ps1.
    echo Keep this button in the job_pipeline folder, then run it again.
    echo.
    pause
    exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" %*
set "STATUS=%ERRORLEVEL%"

if not "%STATUS%"=="0" (
    echo.
    echo Local service launcher exited with code %STATUS%.
    pause
)

exit /b %STATUS%
