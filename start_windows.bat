@echo off
REM ============================================================
REM  سامانه هوشمند جمع‌آوری و آرشیو کانال‌های تلگرام
REM  اجرای برنامه روی ویندوز - کافیست روی این فایل دوبار کلیک کنید
REM ============================================================
chcp 65001 >nul
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    set "PYTHON_CMD=py -3"
) else (
    where python >nul 2>nul
    if %errorlevel%==0 (
        set "PYTHON_CMD=python"
    ) else (
        echo [ERROR] Python 3 not found. Please install Python 3.10+ from python.org
        pause
        exit /b 1
    )
)

if not exist ".venv" (
    echo [1/3] Creating virtual environment ...
    %PYTHON_CMD% -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
)

echo [2/3] Installing dependencies ...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Dependency installation failed. Check your internet connection.
    pause
    exit /b 1
)

echo [3/3] Starting server at http://localhost:8000 ...
start "" http://localhost:8000
".venv\Scripts\python.exe" run.py %*
pause
