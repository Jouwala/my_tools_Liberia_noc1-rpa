@echo off
REM ============================================================
REM  OLBR portable copy - regenerate nginx.conf from .env and run nginx -t
REM  Portable: every path is derived from %~dp0, never a fixed drive.
REM  ASCII-only + CRLF on purpose; non-ASCII breaks cmd parsing.
REM ============================================================
setlocal
cd /d "%~dp0.."
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\write_nginx_conf.ps1"

echo.
echo ---- done. Press any key to close. ----
pause >nul
endlocal
