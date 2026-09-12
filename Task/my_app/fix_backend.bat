@echo off
setlocal enabledelayedexpansion
REM ============================================================
REM  fix_backend.bat  --  one-click repair for port 7038
REM
REM  Symptom it fixes
REM  ---------------
REM  The "RAN 2G/3G/4G Cells KPI" page shows
REM      "no data (please run the RAN Cells KPI sync task)"
REM  even though the sync HAS run and the frontend is up to date.
REM
REM  Reason: the backend listening on port 7038 is still an OLD
REM  process - an orphan left behind by an earlier start. Every new
REM  backend starts fine but cannot bind 7038, dying with
REM      ERROR [Errno 10048] bind 0.0.0.0:7038
REM  so the new /api/ran-cells-kpi/* routes never go live.
REM
REM  The 5-minute self-heal task CANNOT fix this: the orphan runs at
REM  a higher integrity level than the task account, so taskkill is
REM  refused ("insufficient privilege"). Administrator rights are
REM  required - that is what this script is for.
REM
REM  What this script does
REM  ---------------------
REM    1. requests administrator rights (UAC -> click Yes)
REM    2. kills whatever still listens on 7038 (whole process tree)
REM    3. verifies the port is really released
REM    4. removes stale pid / heartbeat files and stopped.flag
REM    5. starts the backend from the CURRENT code (start_hidden.ps1)
REM    6. verifies the new routes are live and writes a report
REM
REM  How to run
REM  ----------
REM    ON THE SERVER (192.168.100.20), double-click:
REM        D:\01_RPA\Task\my_app\fix_backend.bat
REM    Running it from the \\192.168.100.20\01_rpa share does NOT
REM    work - Windows cannot elevate a script that lives on a UNC path.
REM
REM  Report
REM  ------
REM    log\fix_backend_result.txt   (also echoed to the screen)
REM
REM  NOTE: keep this file ASCII-only. Chinese text inside a .bat
REM        breaks cmd parsing and silently corrupts the powershell
REM        command line further down.
REM ============================================================
set "BASE=%~dp0"
set "PORT=7038"
set "REPORT=%BASE%log\fix_backend_result.txt"

REM ---- refuse to run from a network share ----
echo %BASE% | findstr /b /c:"\\\\" >nul 2>&1
if not errorlevel 1 (
    echo [FAIL] This file is running from a network share:
    echo        %BASE%
    echo.
    echo        Windows cannot elevate a script on a UNC path.
    echo        Log in to the server 192.168.100.20 and double-click
    echo        D:\01_RPA\Task\my_app\fix_backend.bat
    echo.
    pause
    exit /b 1
)

pushd "%BASE%" >nul 2>&1
if errorlevel 1 (
    echo [FAIL] Cannot open "%BASE%"
    pause
    exit /b 1
)

> "%REPORT%" echo ===== fix_backend report %date% %time% =====
>>"%REPORT%" echo [*] base = %BASE%

REM ---- 0) administrator check / self-elevate ----
net session >nul 2>&1
if not "%errorlevel%"=="0" (
    >>"%REPORT%" echo [*] not elevated - asking for UAC elevation now
    echo.
    echo ============================================================
    echo   Administrator rights are required to kill the orphan
    echo   process that is holding port %PORT%.
    echo.
    echo   A UAC prompt will appear - click "Yes".
    echo ============================================================
    echo.
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs" >nul 2>&1
    if errorlevel 1 (
        echo [FAIL] Elevation failed or was cancelled.
        echo        Right-click fix_backend.bat and choose
        echo        "Run as administrator" instead.
        echo.
        pause
    )
    popd
    exit /b 0
)
>>"%REPORT%" echo [OK] running with administrator rights

REM ---- 1) who holds the port right now ----
>>"%REPORT%" echo ----- 1) current owner of port %PORT% -----
set "FOUND=0"
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%PORT% " ^| findstr "LISTENING" 2^>nul') do (
    set "FOUND=1"
    >>"%REPORT%" echo [i] port %PORT% held by pid=%%a
    for /f "tokens=1,2 delims=," %%n in ('tasklist /FI "PID eq %%a" /FO CSV /NH 2^>nul') do (
        >>"%REPORT%" echo     image=%%~n
    )
)
if "%FOUND%"=="0" (
    >>"%REPORT%" echo [i] nobody is listening on %PORT% right now
    echo [i] Nobody is listening on %PORT% - nothing to kill.
)

REM ---- 2) kill the owner(s), retry a few rounds ----
>>"%REPORT%" echo ----- 2) killing the owner(s) -----
for /l %%r in (1,1,3) do (
    netstat -ano 2>nul | findstr ":%PORT% " | findstr "LISTENING" >nul 2>&1
    if errorlevel 1 goto port_free
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%PORT% " ^| findstr "LISTENING" 2^>nul') do (
        taskkill /PID %%a /T /F >nul 2>&1
        if !errorlevel!==0 (
            >>"%REPORT%" echo [OK] round %%r: killed pid=%%a
            echo [OK] round %%r: killed pid=%%a
        ) else (
            >>"%REPORT%" echo [FAIL] round %%r: taskkill refused for pid=%%a
            echo [FAIL] round %%r: taskkill refused for pid=%%a
        )
    )
    ping -n 3 127.0.0.1 >nul
)

netstat -ano 2>nul | findstr ":%PORT% " | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 goto port_stuck

:port_free
>>"%REPORT%" echo [OK] port %PORT% is free
echo [OK] Port %PORT% is free.

REM ---- 3) clean stale pid / heartbeat / stop-flag ----
>>"%REPORT%" echo ----- 3) cleaning stale state -----
for %%f in (
    "%BASE%backend\backend_watchdog.pid"
    "%BASE%backend\worker_watchdog.pid"
    "%BASE%backend\worker.pid"
    "%BASE%backend\worker_u.pid"
    "%BASE%backend\worker_n.pid"
    "%BASE%backend\worker_m.pid"
    "%BASE%backend\worker_c.pid"
) do (
    if exist "%%~f" (
        del "%%~f" >nul 2>&1
        >>"%REPORT%" echo [*] removed %%~nxf
    )
)
if exist "%BASE%log\heartbeat_backend_watchdog.json" (
    del "%BASE%log\heartbeat_backend_watchdog.json" >nul 2>&1
    >>"%REPORT%" echo [*] removed heartbeat_backend_watchdog.json
)
if exist "%BASE%backend\stopped.flag" (
    del "%BASE%backend\stopped.flag" >nul 2>&1
    >>"%REPORT%" echo [*] removed stopped.flag (autostart re-enabled)
)

REM ---- 4) start the backend from the current code ----
>>"%REPORT%" echo ----- 4) starting backend from current code -----
echo [*] Starting backend / workers / frontend (hidden)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%BASE%start_hidden.ps1" >nul 2>&1
>>"%REPORT%" echo [*] start_hidden.ps1 finished

set /a W=0
:wait_up
netstat -ano 2>nul | findstr ":%PORT% " | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 goto is_up
if %W% GEQ 60 goto not_up
set /a W+=1
ping -n 2 127.0.0.1 >nul
goto wait_up

:is_up
>>"%REPORT%" echo [OK] port %PORT% is listening again after about %W% seconds
echo [OK] Port %PORT% is listening again.
ping -n 4 127.0.0.1 >nul

REM ---- 5) verify the new routes are live ----
REM  NOTE: FastAPI serves openapi.json as ONE single line, so counting
REM  matching LINES (find /c) always yields 1 even when both routes are
REM  present. Count OCCURRENCES instead.
REM  Also check the code-revision marker that backend/routers/ran_cells_kpi.py
REM  puts in the /cells description: it proves the RUNNING process has the
REM  current code, not just that the routes were registered at some point.
>>"%REPORT%" echo ----- 5) verifying the new routes -----
powershell -NoProfile -Command "try { $p = (Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:%PORT%/openapi.json?cb=%RANDOM%' -TimeoutSec 20).Content; $n = ([regex]::Matches($p, 'ran-cells-kpi')).Count; $m = ([regex]::Matches($p, 'RCK_META_V2')).Count; Write-Output ('ran-cells-kpi occurrences: ' + $n + '  (expected 2)'); Write-Output ('code revision marker RCK_META_V2: ' + $m + '  (expected 1 or more)'); if ($n -ge 2 -and $m -ge 1) { Write-Output 'ROUTE_CHECK: PASS - routes and current code revision are live' } elseif ($n -ge 2) { Write-Output 'ROUTE_CHECK: WARN - routes exist but an OLDER revision is serving; the restart did not reload the module' } else { Write-Output 'ROUTE_CHECK: FAIL - old code is still serving port %PORT%' } } catch { Write-Output ('ROUTE_CHECK: FAIL - cannot reach openapi.json: ' + $_.Exception.Message) }" > "%BASE%log\_fix_routecheck.txt" 2>&1
type "%BASE%log\_fix_routecheck.txt" >> "%REPORT%"

echo.
echo ============================================================
echo   Done. Look for "ROUTE_CHECK: PASS" above.
echo   PASS -> reload the KPI page; the numbers are clickable and
echo           the drill-down shows site / NE / band columns.
echo   WARN -> routes are up but an older code revision is
echo           serving; run stop.bat then start.bat.
echo   FAIL -> send log\fix_backend_result.txt back for analysis.
echo ============================================================
echo.
goto finish

:port_stuck
>>"%REPORT%" echo [FAIL] port %PORT% is STILL held after 3 kill rounds.
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%PORT% " ^| findstr "LISTENING" 2^>nul') do (
    >>"%REPORT%" echo [FAIL] remaining pid=%%a
    for /f "tokens=1,2 delims=," %%n in ('tasklist /FI "PID eq %%a" /FO CSV /NH 2^>nul') do >>"%REPORT%" echo     image=%%~n
)
>>"%REPORT%" echo [i] Even an elevated taskkill was refused. That means the owner is a
>>"%REPORT%" echo [i] protected or SYSTEM-owned process. The reliable fix is a REBOOT
>>"%REPORT%" echo [i] of 192.168.100.20, then start.bat (or just wait 5 minutes).
echo.
echo [FAIL] Port %PORT% is still held even with administrator rights.
echo        See the report for the remaining pid / image name.
echo        The reliable fix is to REBOOT the server, then run start.bat.
echo.

:finish
echo Report written to: %REPORT%
echo.
type "%REPORT%"
echo.
popd
pause
