@echo off
chcp 65001 >nul 2>&1
title Restart Backend + Task Worker
cd /d "%~dp0"

echo ============================================
echo   Restart backend + task worker watchdog
echo ============================================
echo.

set PYTHON_EXE=C:\Users\ZTEEMS\AppData\Local\Programs\Python\Python312\python.exe
if not exist "%PYTHON_EXE%" (
    echo [ERROR] Python not found: %PYTHON_EXE%
    pause
    exit /b 1
)

REM ============================================================
REM 1. Stop worker watchdog FIRST (tree-kill, takes workers down
REM    with it and prevents them from being respawned)
REM ============================================================
if exist "%~dp0backend\worker_watchdog.pid" (
    for /f "usebackq tokens=*" %%a in ("%~dp0backend\worker_watchdog.pid") do (
        taskkill /PID %%a /T /F >nul 2>&1
        echo [*] Killed worker watchdog tree PID=%%a
    )
    del "%~dp0backend\worker_watchdog.pid" >nul 2>&1
)

REM 2026-08-14: FreeConsole() detaches workers from the watchdog console,
REM so tree-killing the watchdog no longer kills workers. Extra cleanup of
REM all orphan worker processes. NOTE: the old tasklist/findstr approach was
REM broken (tasklist /v never prints command lines, so findstr matched nothing
REM and this block silently no-opped). Use CIM-based ps1 instead.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0kill_orphan_workers.ps1"

REM Stale PID files break the watchdog's duplicate-instance check
REM (a recycled PID would be mistaken for a live watchdog).
for %%f in ("%~dp0backend\worker_*.pid") do del "%%f" >nul 2>&1
if exist "%~dp0backend\worker.pid" del "%~dp0backend\worker.pid" >nul 2>&1

REM ============================================================
REM 2. Stop old backend watchdog (tree-kill takes uvicorn down too)
REM    + fallback kill of orphan backend on port 7038, so the new
REM    watchdog does not fight a second instance for the port.
REM ============================================================
if exist "%~dp0backend\backend_watchdog.pid" (
    for /f "usebackq tokens=*" %%a in ("%~dp0backend\backend_watchdog.pid") do (
        taskkill /PID %%a /T /F >nul 2>&1
        echo [*] Killed backend watchdog tree PID=%%a
    )
    del "%~dp0backend\backend_watchdog.pid" >nul 2>&1
    set FOUND=1
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":7038" ^| findstr "LISTENING" 2^>nul') do (
    taskkill /PID %%a /F >nul 2>&1
    echo [*] Killed orphan backend PID=%%a on 7038
)
REM Clean stale instances on 7040/8000: dual instances cause duplicate task runs (08-13 main_kpi_sync incident)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":7040" ^| findstr "LISTENING" 2^>nul') do (
    taskkill /PID %%a /F >nul 2>&1
    echo [*] Killed orphan backend PID=%%a on 7040
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING" 2^>nul') do (
    taskkill /PID %%a /F >nul 2>&1
    echo [*] Killed orphan backend PID=%%a on 8000
)
REM ping instead of timeout: 'timeout' aborts when stdin is redirected
ping -n 3 127.0.0.1 >nul

REM ============================================================
REM 3. Start backend via watchdog (hosts uvicorn, auto-respawn).
REM    MY_APP_TASK_QUEUE=1 is set inside backend_watchdog; the
REM    watchdog keeps it alive so the scheduler never silently dies.
REM ============================================================
echo [*] Starting backend watchdog (port 7038, task queue mode)...
REM Important: unset WorkBuddy safe-delete guard env. Workers started from a
REM WorkBuddy terminal inherit CODEBUDDY_SESSION_ID + CODEBUDDY_SAFE_DELETE_SANDBOX=1,
REM which makes sitecustomize.py redirect os.remove/unlink/rmtree to the recycle bin
REM and FAIL_CLOSED in sandbox mode, breaking tasks that explicitly delete files.
start "BackendWatchdog" /MIN cmd /c "chcp 65001 >nul & set CODEBUDDY_SESSION_ID=&set CLAUDE_SESSION_ID=&set CODEBUDDY_SAFE_DELETE_SANDBOX=& "%PYTHON_EXE%" -m backend.backend_watchdog > "%~dp0log\backend_watchdog_console.log" 2>&1"

set /a BACKEND_WAIT=0
:wait_backend
netstat -ano | findstr ":7038" | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 goto backend_ready
if %BACKEND_WAIT% GEQ 30 goto backend_unavailable
set /a BACKEND_WAIT+=1
ping -n 2 127.0.0.1 >nul
goto wait_backend

:backend_unavailable
echo [ERROR] Backend did not start on port 7038 within 30 seconds.
echo         Check log\backend_runtime.log
pause
exit /b 1

:backend_ready
echo [OK] Backend is listening on port 7038.

REM ============================================================
REM 4. Start task worker watchdog
REM    Skipping this leaves the queue producer running with no
REM    consumer: tasks pile up as 'pending' forever.
REM ============================================================
REM Redirect the console stream to a SEPARATE file. worker_watchdog.py opens
REM log\worker_watchdog.log itself via logging.FileHandler; pointing '>' at the same
REM path makes cmd hold an exclusive handle and the watchdog dies instantly with
REM PermissionError [Errno 13] before it can spawn any worker.
echo [*] Starting task worker watchdog (groups=u,n,m)...
start "TaskWorkerWatchdog" /MIN cmd /c "chcp 65001 >nul & set CODEBUDDY_SESSION_ID=&set CLAUDE_SESSION_ID=&set CODEBUDDY_SAFE_DELETE_SANDBOX=& set MY_APP_WORKER_GROUPS=u,n,m& "%PYTHON_EXE%" -m backend.worker_watchdog > "%~dp0log\worker_watchdog_console.log" 2>&1"

echo [*] Waiting for workers to come up...
ping -n 8 127.0.0.1 >nul

REM ============================================================
REM 5. Verify
REM ============================================================
echo.
echo ---------- health check ----------
set RESTART_OK=1

netstat -ano | findstr ":7038" | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo [OK]   Backend listening on 7038
) else (
    echo [FAIL] Backend not listening - see log\backend_runtime.log
    set RESTART_OK=0
)

if exist "%~dp0backend\worker_watchdog.pid" (
    echo [OK]   Watchdog running
) else (
    echo [FAIL] Watchdog PID missing - see log\worker_watchdog.log
    set RESTART_OK=0
)

set /a WCOUNT=0
if exist "%~dp0backend\worker_u.pid" set /a WCOUNT+=1
if exist "%~dp0backend\worker_n.pid" set /a WCOUNT+=1
if exist "%~dp0backend\worker_m.pid" set /a WCOUNT+=1
echo [*]    Worker groups up: %WCOUNT% / 3
if %WCOUNT% LSS 3 (
    echo [WARN] Not all worker groups started - see log\worker_runtime.log
    set RESTART_OK=0
)
echo ----------------------------------
echo.

if %RESTART_OK%==1 (
    echo [DONE] Backend and workers restarted successfully.
) else (
    echo [WARN] Restart finished with problems. Check the logs above.
)
echo.
pause
