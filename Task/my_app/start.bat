@echo off
chcp 65001 >nul 2>&1
title Data Insight MVP

:: 使用bat文件自身所在目录（支持任意位置运行）
cd /d "%~dp0"

echo ============================================
echo   Data Insight MVP - Starting...
echo ============================================
echo.

:: ===== 自动检测 Python（优先 python.exe 便于看到错误） =====
set PYTHON_EXE=
where python.exe >nul 2>&1
if %errorlevel%==0 (
    for /f "delims=" %%i in ('where python.exe') do (
        if not defined PYTHON_EXE set PYTHON_EXE=%%i
    )
)
if not defined PYTHON_EXE (
    where pythonw.exe >nul 2>&1
    if %errorlevel%==0 (
        for /f "delims=" %%i in ('where pythonw.exe') do (
            if not defined PYTHON_EXE set PYTHON_EXE=%%i
        )
    )
)
if not defined PYTHON_EXE (
    echo [ERROR] Python not found in PATH! Please install Python and add to PATH.
    pause
    exit /b 1
)
echo [*] Python: %PYTHON_EXE%

:: ===== 自动检测 npm =====
set NPM_CMD=npm
where npm.cmd >nul 2>&1
if %errorlevel%==0 set NPM_CMD=npm.cmd

:: 获取本机IP地址
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /C:"IPv4"') do (
    for /f "tokens=1" %%b in ("%%a") do (
        set LOCAL_IP=%%b
        goto :found_ip
    )
)
:found_ip

:: Start backend（带日志，便于排查启动失败）
:: MY_APP_TASK_QUEUE=1：Phase 3 队列模式，定时/手动任务投递 task_queue 由 Worker 执行
:: 注意 set 后紧跟 &（不留空格），否则变量值会带尾部空格导致开关失效
echo [*] Starting backend server (port 7038, task queue mode)...
netstat -ano | findstr ":7038" | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo [*] Backend is already listening on port 7038; reusing it.
) else (
    start "Backend" /MIN cmd /c "chcp 65001 >nul & set MY_APP_TASK_QUEUE=1& "%PYTHON_EXE%" -m uvicorn backend.main:app --host 0.0.0.0 --port 7038 > "%~dp0backend_runtime.log" 2>&1"
)

:: Do not expose the frontend proxy until its backend target is reachable.
:: Otherwise Vite returns 502 (ECONNREFUSED) for the first /api requests.
set /a BACKEND_WAIT=0
:wait_backend
netstat -ano | findstr ":7038" | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 goto backend_ready
if %BACKEND_WAIT% GEQ 30 goto backend_unavailable
set /a BACKEND_WAIT+=1
timeout /t 1 /nobreak >nul
goto wait_backend

:backend_unavailable
echo [ERROR] Backend did not start on port 7038 within 30 seconds.
echo         Check backend_runtime.log before starting the frontend.
pause
exit /b 1

:backend_ready
echo [OK] Backend is listening on port 7038.

:: Start task worker watchdog（托管 backend.worker：崩溃/被杀后自动重拉，避免 Last 冻结）
:: MY_APP_WORKER_GROUPS=u,n,m：三组 worker 并行消费（u=UME 会话组，n=网管/eFlow 组，m=内务轻任务组）；
:: 组内串行与旧行为一致，组间并行（行为等价并发）。改回单 worker：删除该变量即可。
echo [*] Starting task worker watchdog (auto-restart worker, groups=u,n,m)...
start "TaskWorkerWatchdog" /MIN cmd /c "chcp 65001 >nul & set MY_APP_WORKER_GROUPS=u,n,m& "%PYTHON_EXE%" -m backend.worker_watchdog > "%~dp0worker_watchdog.log" 2>&1"

:: Start frontend
echo [*] Starting frontend dev server (port 7090)...
cd frontend
start "Frontend" /MIN cmd /c "%NPM_CMD% run dev > "%~dp0frontend_runtime.log" 2>&1"
cd ..

:: Wait and verify backend
echo [*] Waiting for services to start...
timeout /t 6 /nobreak >nul

:: 检测后端是否存活
netstat -ano | findstr ":7038" | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo [OK] Backend is running on port 7038
) else (
    echo [WARN] Backend may have failed to start! Check backend_runtime.log
    echo        Common causes: port conflict, missing dependencies, Python version issue
    type "%~dp0backend_runtime.log" 2>nul
)

:: 检测看门狗（worker 管理器）是否存活；看门狗负责保活分组 worker
if exist "%~dp0backend\worker_watchdog.pid" (
    echo [OK] Task worker watchdog is running (auto-restart enabled, groups=u,n,m)
) else (
    echo [WARN] Worker watchdog PID file not found! Check worker_watchdog.log
)

:: Auto-open browser
echo [*] Opening browser...
start http://localhost:7090

echo.
echo ============================================
echo   Data Insight MVP is running!
echo ============================================
echo.
echo   Local access:
echo     Frontend: http://localhost:7090
echo     Backend:  http://localhost:7038
echo.
echo   LAN access (for other computers):
echo     Frontend: http://%LOCAL_IP%:7090
echo     Backend:  http://%LOCAL_IP%:7038
echo.
echo   Note: If LAN access fails, run firewall_setup.bat as Administrator
echo ============================================
echo.
echo   Press any key to close this window (services keep running).
echo   Double-click stop.bat to stop all services.
echo.
pause >nul
