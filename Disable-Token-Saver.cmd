@echo off
setlocal
set "taskScript=%~dp0Disable-Token-Saver.ps1"
if not exist "%taskScript%" set "taskScript=%~dp0payload\Disable-Token-Saver.ps1"
if not exist "%taskScript%" (
  echo Extract the complete package before running Disable-Token-Saver.cmd.
  pause
  exit /b 1
)
echo Close Codex completely before continuing. Save other work before the later Windows restart.
echo This disables the bundle and keeps its files and history. It does not restart Windows automatically.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%taskScript%" %*
set "taskExit=%ERRORLEVEL%"
pause
exit /b %taskExit%
