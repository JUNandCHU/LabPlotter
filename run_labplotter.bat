@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo Python 3 was not found.
  echo Install Python 3.10 or newer from https://www.python.org/downloads/windows/
  echo During installation, select "Add python.exe to PATH".
  pause
  exit /b 1
)

set "PY_VERSION="
for %%V in (3.12 3.13 3.11 3.10 3.14) do (
  if not defined PY_VERSION (
    py -%%V -c "import sys; assert sys.version_info >= (3,10)" >nul 2>nul
    if not errorlevel 1 set "PY_VERSION=%%V"
  )
)
if not defined PY_VERSION (
  echo Python 3.10 or newer was not found by the Windows Python launcher.
  echo Run "py -0p" to check the installed versions.
  pause
  exit /b 1
)

echo Using Python %PY_VERSION%...

if not exist ".venv\Scripts\python.exe" (
  echo Creating the local LabPlotter environment...
  py -%PY_VERSION% -m venv .venv
  if errorlevel 1 goto :error
  .venv\Scripts\python.exe -m pip install --upgrade pip
  .venv\Scripts\python.exe -m pip install -e .
  if errorlevel 1 goto :error
)

start "LabPlotter" .venv\Scripts\pythonw.exe -m labplotter
exit /b 0

:error
echo.
echo LabPlotter setup failed. Check the message above.
pause
exit /b 1
