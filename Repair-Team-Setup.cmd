@echo off
setlocal
set "repair_script=%~dp0Repair-Team-Setup.ps1"
if exist "%~dp0payload\Repair-Team-Setup.ps1" set "repair_script=%~dp0payload\Repair-Team-Setup.ps1"
echo Codex Token Saver - repair an existing team installation
echo Preserves installed libraries, component choices, and Codex connection settings.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%repair_script%" %*
set "repair_exit=%ERRORLEVEL%"
if not "%repair_exit%"=="0" echo Repair stopped. Keep the error text above.
pause
exit /b %repair_exit%
