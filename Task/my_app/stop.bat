@echo off
setlocal enabledelayedexpansion
REM ============================================================
REM  stop.bat - fully stop my_app: EVERY process that
REM  start.bat / start_hidden.ps1 / realtime proxy may have started.
REM
REM  Usage:
REM    stop.bat          -> stop all app processes (keep PostgreSQL)
REM    stop.bat all      -> also stop PostgreSQL
REM
REM  Layers (defense in depth, no orphans left behind):
REM    1. tree-kill worker_watchdog / backend_watchdog by PID file
REM    2. kill by port WITH /T (children die too, e.g. uvicorn --reload
REM       reloader's spawned server child)
REM    3. command-line sweep: kill any leftover python/node that runs
REM       my_app modules (orphans whose pid file/port already vanished)
REM    4. delete pid files + heartbeat files
REM    5. verify all ports released, report leftovers
REM    6. optional: stop PostgreSQL (stop.bat all)
REM    7. write backend\stopped.flag (blocks autostart + ensure task)
REM    8. if anything remains, retry the whole stop elevated (UAC)
REM ============================================================
set "BASE=%~dp0"
cd /d "%BASE%"
set "PATH=C:\Program Files\PostgreSQL\16\bin;%PATH%"

REM NOTE: no forced elevation at start. We first stop everything that runs at
REM the current integrity level. If something remains (e.g. PostgreSQL started
REM elevated by the autostart/ensure tasks), we re-run elevated at the end.

echo ============================================
echo   Stopping Data Insight MVP (all tasks)...
echo ============================================

REM ---- 1) Stop watchdog trees first (children die with them) ----
if exist "%BASE%backend\worker_watchdog.pid" (
    for /f "usebackq tokens=*" %%a in ("%BASE%backend\worker_watchdog.pid") do (
        taskkill /PID %%a /T /F >nul 2>&1
        echo [*] Killed worker_watchdog tree PID=%%a
    )
)
if exist "%BASE%backend\backend_watchdog.pid" (
    for /f "usebackq tokens=*" %%a in ("%BASE%backend\backend_watchdog.pid") do (
        taskkill /PID %%a /T /F >nul 2>&1
        echo [*] Killed backend_watchdog tree PID=%%a
    )
)

REM ---- 2) Kill by port (WITH /T so child processes die too) ----
REM NOTE: 8787/8790 已从端口列表移除 —— 它们属于 WorkBuddy 的 MCP 服务
REM       (C:\Users\ZTEEMS\.workbuddy\binaries\python\...\python.exe)，与 my_app 无关。
REM       2026-09-04 实测：stop.bat 曾把它们误杀，险些打断工具链。
REM NOTE: 9268 也已移除（2026-09-11）—— 那是 liberia-noc_soc 门户的 WhatsApp 本地分析
REM       服务，由该门户自己的 stop.bat 负责停止，不属于 my_app。
for %%p in (7038 8000 7040 7090 5173) do (
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%%p " ^| findstr "LISTENING" 2^>nul') do (
        taskkill /PID %%a /T /F >nul 2>&1
        if !errorlevel!==0 (
            echo [*] Killed PID=%%a on port %%p
        ) else (
            echo [WARN] Cannot kill PID=%%a on port %%p - needs administrator rights
        )
    )
)

REM ---- 3) Command-line sweep: leftover python/node from my_app ----
REM Catches orphans whose pid file/port is gone (e.g. workers whose
REM watchdog died, realtime proxies on odd ports). Pattern is specific
REM to my_app modules; unrelated python/node (e.g. MCP servers) survive.
REM NOTE (2026-09-11): the frontend alternative is "my_app.*vite", NOT a bare
REM       "vite" -- the liberia-noc_soc portal also runs a vite dev server
REM       (port 9267), and a bare "vite" killed it whenever my_app was stopped.
echo [*] Scanning for leftover my_app processes...
powershell -NoProfile -Command ^
  "$pat='backend\.worker_watchdog|backend\.backend_watchdog|backend\.worker|uvicorn.*backend\.main|realtime_proxy|start-app\.mjs|my_app.*vite';" ^
  "$n=0;" ^
  "Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'python|node' -and $_.CommandLine -match $pat -and $_.ProcessId -ne $PID } | ForEach-Object { taskkill /PID $_.ProcessId /T /F 2>$null | Out-Null; Write-Host ('[*] Killed leftover ' + $_.Name + ' PID=' + $_.ProcessId); $n++ };" ^
  "if ($n -eq 0) { Write-Host '[OK] No leftover my_app processes found.' }"

REM ---- 4) Cleanup pid files and heartbeat files ----
for %%f in ("%BASE%backend\worker_*.pid" "%BASE%backend\worker.pid" "%BASE%backend\backend_watchdog.pid") do (
    if exist "%%~f" del "%%~f" >nul 2>&1
)
del "%BASE%log\heartbeat_*.json" >nul 2>&1

REM ---- 5) Verify all ports released ----
set LEFTOVER=0
for %%p in (7038 8000 7040 7090 5173) do (
    netstat -ano | findstr ":%%p " | findstr "LISTENING" >nul 2>&1
    if !errorlevel!==0 (
        echo [FAIL] Port %%p still listening
        set LEFTOVER=1
    )
)
if %LEFTOVER%==1 (
    echo.
    echo [FAIL] Some processes failed to stop. Remaining listeners:
    netstat -ano | findstr "LISTENING" | findstr ":7038 :8000 :7040 :7090 :5173"
) else (
    echo [OK] All app ports released.
)

REM ---- 6) Optional: stop PostgreSQL (stop.bat all) ----
if /i not "%~1"=="all" goto pg_keep

REM 6a) try clean shutdown via pg_ctl first
netstat -ano | findstr ":5432" | findstr "LISTENING" >nul 2>&1
if errorlevel 1 (
    echo [OK] PostgreSQL not running.
    goto pg_done
)
pg_ctl stop -D "C:\Program Files\PostgreSQL\16\data" -m fast >nul 2>&1

REM 6b) wait up to 30s for release (ping is a console-free sleep; timeout fails
REM     when stdin is redirected, e.g. from scheduled tasks)
set /a PGWAIT=0
:wait_pg_stop
netstat -ano | findstr ":5432" | findstr "LISTENING" >nul 2>&1
if errorlevel 1 goto pg_stopped
if %PGWAIT% GEQ 30 goto pg_stop_force
set /a PGWAIT+=1
ping -n 2 127.0.0.1 >nul
goto wait_pg_stop

:pg_stop_force
REM 6c) pg_ctl could not stop it (e.g. runs under another account) - force kill
echo [WARN] pg_ctl could not stop PostgreSQL gracefully - force stopping postmaster...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5432 " ^| findstr "LISTENING" 2^>nul') do (
    taskkill /PID %%a /T /F >nul 2>&1
    echo [*] Force-killed postmaster tree PID=%%a
)
ping -n 3 127.0.0.1 >nul
netstat -ano | findstr ":5432" | findstr "LISTENING" >nul 2>&1
if errorlevel 1 (
    echo [OK] PostgreSQL stopped - force kill.
    goto pg_done
)
echo [FAIL] PostgreSQL still listening on 5432 - stop it manually
set LEFTOVER=1
goto pg_done

:pg_stopped
echo [OK] PostgreSQL stopped.
goto pg_done

:pg_keep
echo [*] PostgreSQL left running - use "stop.bat all" to stop it too.
:pg_done

REM ---- 7) Stop marker: blocks autostart / ensure task until next start ----
echo %date% %time% stopped by %USERNAME%> "%BASE%backend\stopped.flag"
echo [*] Wrote backend\stopped.flag - autostart and ensure-task are blocked.

REM ---- 8) If something remains, retry the whole stop ELEVATED ----
REM (PostgreSQL is started elevated by the logon autostart task; an unelevated
REM shell cannot kill it. Only elevate when really needed, so plain
REM "stop.bat" for a normally-started app needs no UAC prompt.)
if %LEFTOVER%==0 (
    echo [*] All my_app processes stopped.
    exit /b 0
)
net session >nul 2>&1
if %errorlevel%==0 (
    echo [FAIL] Some processes could not be stopped even as administrator - check the list above.
    exit /b 1
)
echo [*] Some processes need administrator rights to stop (e.g. elevated PostgreSQL).
echo     Retrying with elevation - please click "Yes" on the UAC prompt.
powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '%*' -Verb RunAs -Wait" >nul 2>&1
exit /b 0
