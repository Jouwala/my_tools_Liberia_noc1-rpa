@echo off
REM OLBR portable copy - stop everything this copy started.
REM Never touches the production instance on the source machine.
REM Keep this file ASCII-only and CRLF.
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop_all.ps1" %*
endlocal