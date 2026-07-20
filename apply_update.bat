@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
  echo LabPlotter's local Python environment was not found.
  echo Run run_labplotter.bat once before applying an update.
  pause
  exit /b 1
)

start "LabPlotter Update Manager" ".venv\Scripts\pythonw.exe" "updater.py" --app-root "%CD%"

