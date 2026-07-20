@echo off
setlocal
cd /d "%~dp0"

set "PY_VERSION="
for %%V in (3.12 3.13 3.11 3.10 3.14) do (
  if not defined PY_VERSION (
    py -%%V -c "import sys; assert sys.version_info >= (3,10)" >nul 2>nul
    if not errorlevel 1 set "PY_VERSION=%%V"
  )
)
if not defined PY_VERSION goto :no_python

if not exist ".buildvenv\Scripts\python.exe" py -%PY_VERSION% -m venv .buildvenv
.buildvenv\Scripts\python.exe -m pip install --upgrade pip
.buildvenv\Scripts\python.exe -m pip install -r requirements-build.txt
if errorlevel 1 goto :error

.buildvenv\Scripts\pyinstaller.exe --noconfirm --clean --windowed --onedir ^
  --name LabPlotter ^
  --collect-all matplotlib ^
  --collect-all scipy ^
  --hidden-import PIL._tkinter_finder ^
  launcher.py
if errorlevel 1 goto :error

echo.
echo Build completed: dist\LabPlotter\LabPlotter.exe
pause
exit /b 0

:error
echo.
echo Windows build failed. Check the message above.
pause
exit /b 1

:no_python
echo Python 3.10 or newer was not found by the Windows Python launcher.
pause
exit /b 1
