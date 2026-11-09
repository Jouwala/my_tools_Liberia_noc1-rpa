@echo off
REM ============================================================
REM  OLBR portable copy - preview the start plan without starting anything
REM  Portable: every path is derived from %~dp0, never a fixed drive.
REM  ASCII-only + CRLF on purpose; non-ASCII breaks cmd parsing.
REM ============================================================
setlocal
cd /d "%~dp0.."
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\scripts\start_all.ps1" -DryRun

echo.
echo ---- done. Press any key to close. ----
pause >nul
endlocal
