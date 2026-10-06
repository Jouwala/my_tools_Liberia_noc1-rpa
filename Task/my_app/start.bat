@echo off
title Data Insight MVP

:: Use the directory of this bat file (can be run from anywhere)
cd /d "%~dp0"

echo ============================================
echo   Data Insight MVP - Starting...
echo ============================================
echo.

:: ===== Clear stop marker (stopped.flag written by stop.bat blocks autostart; manual start clears it) =====
if exist "%~dp0backend\stopped.flag" (
    del "%~dp0backend\stopped.flag" >nul 2>&1
    echo [*] Cleared stopped.flag - autostart re-enabled.
)

:: ===== Start backend / watchdogs / frontend hidden =====
:: Delegate to start_hidden.ps1 (powershell Start-Process -WindowStyle Hidden).
:: Do NOT rely on wscript/vbs here (blocked by security policy on this box).
:: NOTE: keep this bat ASCII-only. UTF-8 Chinese breaks cmd batch parsing
:: and silently corrupts the powershell command line below.
echo [*] Starting backend / worker / frontend hidden...
:: MY_PORTAL_NO_POPUP is set by the desktop-shortcut controller
:: (D:\01_RPA\my_portal_ctl.ps1) when it drives this bat. In that mode we must
:: pass -Quiet, otherwise start_hidden.ps1 opens a modal MessageBox on any
:: warning and BLOCKS until someone clicks it - the dialog can open behind other
:: windows, which made 4-start_myapp / 8-start_all look like they never start.
:: The controller clears backend\stopped.flag before calling, so -Quiet's
:: stop-flag check cannot wrongly skip a start the operator asked for.
set "_PSQUIET="
if defined MY_PORTAL_NO_POPUP set "_PSQUIET=-Quiet"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_hidden.ps1" %_PSQUIET%

:: Wait for backend (otherwise frontend proxy gets 502)
:: MY_PORTAL_NO_PAUSE (set by my_portal_ctl.ps1) makes this bat run with its
:: output captured by the controller, so it must not use `timeout` - Windows'
:: timeout.exe refuses to run without a console ("ERROR: Input redirection is
:: not supported"). `ping -n N 127.0.0.1` is the classic redirect-safe sleep.
set /a BACKEND_WAIT=0
:wait_backend
netstat -ano 2>nul | findstr ":7038" | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 goto backend_ready
if %BACKEND_WAIT% GEQ 30 goto backend_unavailable
set /a BACKEND_WAIT+=1
:: Sleep 1s. Two spellings on purpose: `timeout` only works with a real console
:: (it aborts with "Input redirection is not supported" when the controller
:: captures our output), and `ping -n` is the redirect-safe equivalent.
:: Written as separate `if` + `goto` lines rather than `if defined X (a) else (b)`
:: because that one-line parenthesised form mis-parses under cmd and silently
:: ran the wrong branch here (observed 2026-10-06).
if defined MY_PORTAL_NO_PAUSE goto sleep_ping_1
timeout /t 1 /nobreak >nul
goto wait_backend
:sleep_ping_1
ping -n 2 127.0.0.1 >nul
goto wait_backend

:backend_unavailable
echo [ERROR] Backend did not start on port 7038 within 30 seconds.
echo         Check log\backend_runtime.log
if not defined MY_PORTAL_NO_PAUSE pause
exit /b 1

:backend_ready
echo [OK] Backend is listening on port 7038.

if defined MY_PORTAL_NO_PAUSE goto settle_ping
timeout /t 6 /nobreak >nul
goto after_settle
:settle_ping
ping -n 7 127.0.0.1 >nul
:after_settle

netstat -ano 2>nul | findstr ":7038" | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo [OK] Backend is running on port 7038
) else (
    echo [WARN] Backend may have failed to start! Check log\backend_runtime.log
)

:: Parens inside an echo that lives in an `if (...)` block MUST be escaped,
:: otherwise the first ^) closes the block early and cmd tries to run the
:: remainder of the line as a command ("and was unexpected at this time.").
:: (Note: use `rem` for comments inside a block - a `::` label there makes cmd
::  emit "The system cannot find the drive specified." and misparse the block.)
if exist "%~dp0backend\worker_watchdog.pid" (
    echo [OK] Task worker watchdog is running ^(auto-restart enabled, groups=u,n,s,w,m,c,v^)
) else (
    echo [WARN] Worker watchdog PID file not found! Check log\worker_watchdog_console.log
)

:: Worker group check. The group list MUST match
::   start_hidden.ps1 MY_APP_WORKER_GROUPS, worker_watchdog.GROUP_TASK_MAP
::   (restart_workers.ALL_GROUPS derives from GROUP_TASK_MAP).
:: Previously v was omitted here, so a dead v-group still reported "4 / 4" all-green.
:: 2026-09-27: n 拆为 n/s/w 后同步补 s、w 两项，否则 s/w 组死了仍报 all-green。
set /a WCOUNT=0
if exist "%~dp0backend\worker_u.pid" set /a WCOUNT+=1
if exist "%~dp0backend\worker_n.pid" set /a WCOUNT+=1
if exist "%~dp0backend\worker_s.pid" set /a WCOUNT+=1
if exist "%~dp0backend\worker_w.pid" set /a WCOUNT+=1
if exist "%~dp0backend\worker_m.pid" set /a WCOUNT+=1
if exist "%~dp0backend\worker_c.pid" set /a WCOUNT+=1
if exist "%~dp0backend\worker_v.pid" set /a WCOUNT+=1
echo [*] Worker groups up: %WCOUNT% / 7
if %WCOUNT% LSS 7 (
    echo [WARN] Task queue has no full consumer set! Tasks will pile up as pending.
    echo        Check log\worker_runtime*.log ^(one per group^) and log\worker_watchdog.log
)

echo.
echo ============================================
echo   Data Insight MVP is running!
echo ============================================
echo.
echo   Local access:
echo     Frontend: http://localhost:7090
echo     Backend:  http://localhost:7038
echo.
:: When driven by my_portal_ctl.ps1 the controller owns the "press Enter"
:: prompt (that way the operator reads every stage in one window and presses
:: Enter exactly once). Pausing here too would block the controller's
:: Start-Process -Wait and make the shortcut look like it had hung.
if not defined MY_PORTAL_NO_PAUSE (
    echo   Press Enter to close this window ^(services keep running^).
    echo   Double-click stop.bat to stop all services.
    echo.
    pause >nul
)
