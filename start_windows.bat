@echo off
REM ==========================================================
REM  Telegram Channel Collector - Windows launcher
REM  Double-click this file to start the program.
REM  All real logic lives in launcher.py, because cmd.exe is
REM  too fragile for non-ASCII text and nested if-blocks.
REM ==========================================================
chcp 65001 >nul 2>nul
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" goto :run

set PY=
py -3 -c "import sys;sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>nul
if not errorlevel 1 set PY=py -3

if not defined PY (
    python -c "import sys;sys.exit(0 if sys.version_info>=(3,10) else 1)" >nul 2>nul
    if not errorlevel 1 set PY=python
)

if defined PY goto :run

echo.
echo  Python 3.10 or newer was not found on this computer.
echo  Install it from https://www.python.org/downloads/
echo  During setup, tick: Add python.exe to PATH
echo.
pause
exit /b 1

:run
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" launcher.py %*
) else (
    %PY% launcher.py %*
)
set RC=%errorlevel%

echo.
if not %RC%==0 echo  The program exited with an error code %RC%. See messages above.
pause
endlocal & exit /b %RC%
