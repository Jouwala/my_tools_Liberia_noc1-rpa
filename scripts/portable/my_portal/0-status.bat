@echo off
REM ============================================================
REM  OLBR portable copy - check ports and entry URLs
REM  Portable: every path is derived from %~dp0, never a fixed drive.
REM  ASCII-only + CRLF on purpose; non-ASCII breaks cmd parsing.
REM ============================================================
setlocal
cd /d "%~dp0.."
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0status.ps1"

echo.
echo ---- done. Press any key to close. ----
pause >nul
endlocal
