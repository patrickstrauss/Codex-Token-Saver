@echo off
setlocal
set "setup_script=%~dp0Setup-Request-Compression.ps1"
if not exist "%setup_script%" set "setup_script=%~dp0payload\Setup-Request-Compression.ps1"
if not exist "%setup_script%" (
  echo Request compression setup is missing. Extract the complete deployment artifact first.
  pause
  exit /b 1
)
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%setup_script%" %*
set "setup_exit=%errorlevel%"
pause
exit /b %setup_exit%
