@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Upgrade-App.ps1" %*
if errorlevel 1 echo Upgrade did not complete. Keep the error above.
pause
