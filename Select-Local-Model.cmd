@echo off
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Select-Local-Model.ps1"
if errorlevel 1 pause
