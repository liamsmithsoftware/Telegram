@echo off
REM ============================================================
REM  سامانه هوشمند جمع‌آوری و آرشیو کانال‌های تلگرام
REM  اجرای برنامه روی ویندوز - کافیست روی این فایل دوبار کلیک کنید
REM
REM  این اسکریپت هیچ نیازی به Microsoft C++ Build Tools ندارد،
REM  چون وابستگی‌های کامپایل‌شونده را نصب نمی‌کند.
REM ============================================================
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "PYTHON_CMD="
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
    if !errorlevel!==0 set "PYTHON_CMD=py -3"
)
if not defined PYTHON_CMD (
    where python >nul 2>nul
    if !errorlevel!==0 set "PYTHON_CMD=python"
)
if not defined PYTHON_CMD (
    echo.
    echo [ERROR] Python 3.10 or newer was not found.
    echo         Download it from https://www.python.org/downloads/
    echo         IMPORTANT: tick "Add python.exe to PATH" during installation.
    echo.
    pause
    exit /b 1
)

echo [1/3] Checking virtual environment ...
if not exist ".venv\Scripts\python.exe" (
    echo       Creating .venv ...
    %PYTHON_CMD% -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create the virtual environment.
        pause
        exit /b 1
    )
)

echo [2/3] Installing dependencies ...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul 2>nul

".venv\Scripts\python.exe" -m pip install --prefer-binary --retries 5 --timeout 60 -r requirements.txt
if errorlevel 1 (
    echo.
    echo [ERROR] Dependency installation failed.
    echo         - Check your internet / proxy connection.
    echo         - Try running this file again; pip caches partial downloads.
    echo         - Manual fix:
    echo             .venv\Scripts\python.exe -m pip install --prefer-binary -r requirements.txt
    echo.
    pause
    exit /b 1
)

REM موتور اختیاری Telethon — نبودنش برنامه را متوقف نمی‌کند
".venv\Scripts\python.exe" -c "import telethon" >nul 2>nul
if errorlevel 1 (
    echo       Installing optional Telethon engine for private channels ...
    ".venv\Scripts\python.exe" -m pip install --prefer-binary -r requirements-telethon.txt
    if errorlevel 1 (
        echo [WARN] Telethon was not installed. Public channels still work via the web engine.
    )
)

echo [3/3] Starting server at http://localhost:8000 ...
start "" http://localhost:8000
".venv\Scripts\python.exe" run.py %*
pause
