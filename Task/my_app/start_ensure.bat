@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"

REM ============================================================
REM  start_ensure.bat - "MyApp_EnsureRunning" scheduled task entry
REM  Runs every 5 minutes (see install_ensure_task.bat).
REM  - Ensures PostgreSQL is up (it is NOT a Windows service)
REM  - Runs start_hidden.ps1 -Quiet -Force : idempotent; revives
REM    dead/hung backend_watchdog / worker_watchdog / workers.
REM  - Respects backend\stopped.flag (stop.bat stops the app for good).
REM ============================================================

REM Make Python + npm + PostgreSQL binaries reachable in a restricted task PATH.
set "PATH=C:\Users\ZTEEMS\AppData\Local\Programs\Python\Python312;C:\Users\ZTEEMS\AppData\Local\Programs\Python\Python312\Scripts;C:\Users\ZTEEMS\AppData\Roaming\npm;C:\Program Files\PostgreSQL\16\bin;%PATH%"

REM ---- 1. Ensure PostgreSQL (wait for it to accept connections) ----
netstat -ano | findstr ":5432" | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 goto app
pg_ctl start -D "C:\Program Files\PostgreSQL\16\data" -l "%~dp0log\pg_ensure.log" >nul 2>&1
set /a PGWAIT=0
:waitpg
netstat -ano | findstr ":5432" | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 goto app
if %PGWAIT% GEQ 30 goto app
set /a PGWAIT+=1
ping -n 2 127.0.0.1 >nul
goto waitpg

:app
REM ---- 2. Ensure backend / workers / frontend (idempotent) ----
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_hidden.ps1" -Quiet -Force

exit /b 0
