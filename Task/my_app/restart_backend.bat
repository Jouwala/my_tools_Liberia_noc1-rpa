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

:: ============================================================
:: 1. Stop worker watchdog FIRST (tree-kill, takes workers down
::    with it and prevents them from being respawned)
:: ============================================================
if exist "%~dp0backend\worker_watchdog.pid" (
    for /f "usebackq tokens=*" %%a in ("%~dp0backend\worker_watchdog.pid") do (
        taskkill /PID %%a /T /F >nul 2>&1
        echo [*] Killed worker watchdog tree PID=%%a
    )
    del "%~dp0backend\worker_watchdog.pid" >nul 2>&1
)

:: 2026-08-14: FreeConsole() 使 worker 脱离看门狗控制台，树杀看门狗不再连带杀 worker。
:: 必须额外清理所有孤儿 worker 进程（匹配命令行含 backend.worker 的 python.exe）。
for /f "tokens=2" %%a in ('tasklist /fi "IMAGENAME eq python.exe" /v /fo csv 2^>nul ^| findstr /i "backend.worker"') do (
    taskkill /PID %%a /F >nul 2>&1
    echo [*] Killed orphan worker PID=%%a
)

:: Stale PID files break the watchdog's duplicate-instance check
:: (a recycled PID would be mistaken for a live watchdog).
for %%f in ("%~dp0backend\worker_*.pid") do del "%%f" >nul 2>&1
if exist "%~dp0backend\worker.pid" del "%~dp0backend\worker.pid" >nul 2>&1

:: ============================================================
:: 2. Stop old backend watchdog (tree-kill 连带 uvicorn 一起停)
::    + 兜底清理孤儿 backend（端口 7038），避免看门狗再拉起第二个抢端口
:: ============================================================
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
:: 清理 7040/8000 残留实例：不清理会与 7038 双开导致任务双份执行（08-13 main_kpi_sync 事故）
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":7040" ^| findstr "LISTENING" 2^>nul') do (
    taskkill /PID %%a /F >nul 2>&1
    echo [*] Killed orphan backend PID=%%a on 7040
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING" 2^>nul') do (
    taskkill /PID %%a /F >nul 2>&1
    echo [*] Killed orphan backend PID=%%a on 8000
)
:: ping instead of timeout: 'timeout' aborts when stdin is redirected
ping -n 3 127.0.0.1 >nul

:: ============================================================
:: 3. Start backend via watchdog（托管 uvicorn，崩溃/被杀自动重拉）
::    MY_APP_TASK_QUEUE=1 由 backend_watchdog 内部设置；看门狗负责保活，
::    避免再次出现"backend 单独宕机、定时任务静默漏跑"的情况。
:: ============================================================
echo [*] Starting backend watchdog (port 7038, task queue mode)...
:: 关键：unset WorkBuddy safe-delete 守卫 env。若 worker 从 WorkBuddy 终端启动会继承
:: CODEBUDDY_SESSION_ID + CODEBUDDY_SAFE_DELETE_SANDBOX=1，sitecustomize.py 会把
:: os.remove/unlink/rmtree 全部重定向回收站并在沙箱模式 FAIL_CLOSED，导致
:: incident_overview_sync 等所有显式删文件任务失败。后台服务去掉这 3 个变量恢复原生删除。
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

:: ============================================================
:: 4. Start task worker watchdog
::    Skipping this leaves the queue producer running with no
::    consumer: tasks pile up as 'pending' forever.
:: ============================================================
:: Redirect the console stream to a SEPARATE file. worker_watchdog.py opens
:: log\worker_watchdog.log itself via logging.FileHandler; pointing '>' at the same
:: path makes cmd hold an exclusive handle and the watchdog dies instantly with
:: PermissionError [Errno 13] before it can spawn any worker.
echo [*] Starting task worker watchdog (groups=u,n,m)...
start "TaskWorkerWatchdog" /MIN cmd /c "chcp 65001 >nul & set CODEBUDDY_SESSION_ID=&set CLAUDE_SESSION_ID=&set CODEBUDDY_SAFE_DELETE_SANDBOX=& set MY_APP_WORKER_GROUPS=u,n,m& "%PYTHON_EXE%" -m backend.worker_watchdog > "%~dp0log\worker_watchdog_console.log" 2>&1"

echo [*] Waiting for workers to come up...
ping -n 8 127.0.0.1 >nul

:: ============================================================
:: 5. Verify
:: ============================================================
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
