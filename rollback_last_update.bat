@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
  echo LabPlotter's local Python environment was not found.
  pause
  exit /b 1
)

start "LabPlotter Rollback" ".venv\Scripts\pythonw.exe" "updater.py" --app-root "%CD%" --rollback latest

