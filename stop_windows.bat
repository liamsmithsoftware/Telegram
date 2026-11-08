@echo off
REM ============================================================
REM  Telegram Channel Collector - stop running instances
REM  Use this when you see: WinError 10048 / port already in use
REM ============================================================
chcp 65001 >nul 2>nul
setlocal
cd /d "%~dp0"

echo.
echo  Looking for running instances of the program ...
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command "$found = $false; Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'run\.py' -or $_.CommandLine -match 'launcher\.py' } | ForEach-Object { if ($_.ProcessId -ne $PID) { Write-Host ('  Stopping PID ' + $_.ProcessId); try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop; $found = $true } catch {} } }; if ($found) { Write-Host ''; Write-Host '  Done. You can start the program again with start_windows.bat' } else { Write-Host '  No running instance of this program was found.'; Write-Host '  Another program may be using port 8000.' }"

echo.
echo  You can also start on another port:
echo      start_windows.bat --port 8010
echo.
pause
endlocal
