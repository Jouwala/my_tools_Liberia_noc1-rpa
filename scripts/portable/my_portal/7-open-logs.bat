@echo off
REM ============================================================
REM  OLBR portable copy - open the runtime log/TMP folders
REM  Portable: every path is derived from %~dp0, never a fixed drive.
REM  ASCII-only + CRLF on purpose; non-ASCII breaks cmd parsing.
REM ============================================================
setlocal
cd /d "%~dp0.."
if exist "%~dp0..\TMP" (
  start "" explorer.exe "%~dp0..\TMP"
) else (
  echo TMP\ not created yet - run 1-start-all.bat first.
)
echo nginx logs: %~dp0..\nginx-1.28.0\logs\

echo.
echo ---- done. Press any key to close. ----
pause >nul
endlocal
