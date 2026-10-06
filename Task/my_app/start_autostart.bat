@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"

REM ============================================================
REM  start_autostart.bat - logon autostart entry (MyApp_AutoStart)
REM  Ensures PostgreSQL is up, then launches backend / workers /
REM  frontend hidden via start_hidden.ps1 -Quiet.
REM  -Quiet: no popup at logon; respects backend\stopped.flag
REM  (if stop.bat was run, autostart is skipped until next start).
REM ============================================================

REM Make Python + npm + PostgreSQL binaries reachable even in a restricted task PATH.
set "PATH=C:\Users\ZTEEMS\AppData\Local\Programs\Python\Python312;C:\Users\ZTEEMS\AppData\Local\Programs\Python\Python312\Scripts;C:\Users\ZTEEMS\AppData\Roaming\npm;C:\Program Files\PostgreSQL\16\bin;%PATH%"

set "PYTHON_EXE=C:\Users\ZTEEMS\AppData\Local\Programs\Python\Python312\python.exe"

REM ---- 1. Ensure PostgreSQL is running (it is NOT a Windows service) ----
netstat -ano | findstr ":5432" | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo [*] PostgreSQL already listening on 5432.
    goto backend
)
echo [*] Starting PostgreSQL...
pg_ctl start -D "C:\Program Files\PostgreSQL\16\data" -l "%~dp0log\pg_autostart.log" >nul 2>&1
set /a PGWAIT=0
:waitpg
netstat -ano | findstr ":5432" | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 goto pgready
if %PGWAIT% GEQ 30 goto pgfail
set /a PGWAIT+=1
ping -n 2 127.0.0.1 >nul
goto waitpg
:pgfail
echo [WARN] PostgreSQL did not start within 30s. Check log\pg_autostart.log
goto backend
:pgready
echo [OK] PostgreSQL is up.
echo.

:backend
REM ---- 2. Launch backend / worker / frontend hidden (idempotent, quiet) ----
REM start_hidden.ps1 starts only missing components and writes
REM log\start_hidden_result.txt; -Quiet suppresses the popup at logon.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_hidden.ps1" -Quiet
echo [*] Launch sequence complete. All services run hidden; no window to close.
exit /b 0
