@echo off
setlocal
cd /d "%~dp0"
echo Codex Token Saver - per-user Windows installer
echo Installs local tools. Codex keeps its existing connection and settings.
echo No administrator privileges are needed. First install requires internet.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install.ps1" %*
set "install_exit=%ERRORLEVEL%"
if not "%install_exit%"=="0" echo Installation stopped. Read the error above; rerun this launcher to retry.
pause
exit /b %install_exit%
