@echo off
cd /d "%USERPROFILE%"
if exist "%~dp0Uninstall-Token-Saver.ps1" (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Uninstall-Token-Saver.ps1" %*
) else (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%USERPROFILE%\CodexTokenSaver\Uninstall-Token-Saver.ps1" %*
)
if errorlevel 1 echo Uninstall did not finish. Read the recovery instructions above, then retry.
pause
