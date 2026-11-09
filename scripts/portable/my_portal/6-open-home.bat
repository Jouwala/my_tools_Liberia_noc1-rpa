@echo off
REM ============================================================
REM  OLBR portable copy - open the https://localhost/ service navigation page
REM  Portable: every path is derived from %~dp0, never a fixed drive.
REM  ASCII-only + CRLF on purpose; non-ASCII breaks cmd parsing.
REM ============================================================
setlocal
cd /d "%~dp0.."
set "HTTPS_PORT=443"
for /f "usebackq tokens=1,* delims==" %%A in ("%~dp0..\.env") do if /i "%%A"=="NGINX_HTTPS_PORT" set "HTTPS_PORT=%%B"
set "URL=https://localhost:%HTTPS_PORT%/"
if "%HTTPS_PORT%"=="443" set "URL=https://localhost/"
echo Opening %URL% ...
start "" "%URL%"

echo.
echo ---- done. Press any key to close. ----
pause >nul
endlocal
