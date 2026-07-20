@echo off
setlocal
cd /d "%~dp0"

set "DOWNLOAD_DIR=%CD%\.updates\latest"
set "UPDATER=%DOWNLOAD_DIR%\updater_latest.py"
set "PATCH=%DOWNLOAD_DIR%\LabPlotter_Latest.labpatch"
set "UPDATER_URL=https://raw.githubusercontent.com/JUNandCHU/LabPlotter/main/updater.py"
set "PATCH_URL=https://raw.githubusercontent.com/JUNandCHU/LabPlotter/main/updates/LabPlotter_Latest.labpatch"

if not exist ".venv\Scripts\python.exe" (
  echo LabPlotter's local Python environment was not found.
  echo Run run_labplotter.bat once, close LabPlotter, then try again.
  pause
  exit /b 1
)

echo Downloading the latest verified updater and cumulative patch...
if not exist "%DOWNLOAD_DIR%" mkdir "%DOWNLOAD_DIR%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -UseBasicParsing '%UPDATER_URL%' -OutFile '%UPDATER%'; Invoke-WebRequest -UseBasicParsing '%PATCH_URL%' -OutFile '%PATCH%'"
if errorlevel 1 (
  echo Download failed. Check the internet connection and try again.
  pause
  exit /b 1
)

".venv\Scripts\python.exe" "%UPDATER%" --patch "%PATCH%" --app-root "%CD%"
if errorlevel 1 pause

