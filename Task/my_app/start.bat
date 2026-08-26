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
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_hidden.ps1"

:: Wait for backend (otherwise frontend proxy gets 502)
set /a BACKEND_WAIT=0
:wait_backend
netstat -ano 2>nul | findstr ":7038" | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 goto backend_ready
if %BACKEND_WAIT% GEQ 30 goto backend_unavailable
set /a BACKEND_WAIT+=1
timeout /t 1 /nobreak >nul
goto wait_backend

:backend_unavailable
echo [ERROR] Backend did not start on port 7038 within 30 seconds.
echo         Check log\backend_runtime.log
pause
exit /b 1

:backend_ready
echo [OK] Backend is listening on port 7038.

timeout /t 6 /nobreak >nul

netstat -ano 2>nul | findstr ":7038" | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo [OK] Backend is running on port 7038
) else (
    echo [WARN] Backend may have failed to start! Check log\backend_runtime.log
)

if exist "%~dp0backend\worker_watchdog.pid" (
    echo [OK] Task worker watchdog is running (auto-restart enabled, groups=u,n,m,c)
) else (
    echo [WARN] Worker watchdog PID file not found! Check log\worker_watchdog_console.log
)

set /a WCOUNT=0
if exist "%~dp0backend\worker_u.pid" set /a WCOUNT+=1
if exist "%~dp0backend\worker_n.pid" set /a WCOUNT+=1
if exist "%~dp0backend\worker_m.pid" set /a WCOUNT+=1
if exist "%~dp0backend\worker_c.pid" set /a WCOUNT+=1
echo [*] Worker groups up: %WCOUNT% / 4
if %WCOUNT% LSS 4 (
    echo [WARN] Task queue has no full consumer set! Tasks will pile up as pending.
    echo        Check log\worker_runtime.log and log\worker_watchdog.log
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
echo   Press any key to close this window (services keep running).
echo   Double-click stop.bat to stop all services.
echo.
pause >nul
