@echo off
rem ---------------------------------------------------------------------
rem  Drift Tool - double click launcher
rem  Starts the local app and opens it in the default browser.
rem ---------------------------------------------------------------------
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo.
  echo  Python was not found on this computer.
  echo  Install Python 3 from https://www.python.org/downloads/ and run this again.
  echo  During installation tick "Add python.exe to PATH".
  echo.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment ...
  python -m venv .venv
  if errorlevel 1 goto failed
  ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
  ".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
)

echo Starting Drift Tool ...
".venv\Scripts\python.exe" server.py
if errorlevel 1 goto failed
exit /b 0

:failed
echo.
echo  The app could not start. Run this file from a command prompt to see the error.
echo.
pause
exit /b 1
