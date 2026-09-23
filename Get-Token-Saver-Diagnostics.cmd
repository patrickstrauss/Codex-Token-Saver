@echo off
setlocal
set "diagnostic_script=%~dp0Get-Token-Saver-Diagnostics.ps1"
if not exist "%diagnostic_script%" set "diagnostic_script=%~dp0payload\Get-Token-Saver-Diagnostics.ps1"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%diagnostic_script%" %*
set "diagnostic_exit=%errorlevel%"
pause
exit /b %diagnostic_exit%
