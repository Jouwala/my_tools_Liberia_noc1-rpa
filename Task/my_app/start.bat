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
:: 0) 项目内嵌 Python（终极兜底：拷贝到任何机器都能跑；该目录不存在则跳过）
if exist "%~dp0bin\python\python.exe" set PYTHON_EXE=%~dp0bin\python\python.exe
:: 1) PATH 中的 python
if not defined PYTHON_EXE (
    where python.exe >nul 2>&1
    if %errorlevel%==0 (
        for /f "delims=" %%i in ('where python.exe') do (
            if not defined PYTHON_EXE set PYTHON_EXE=%%i
        )
    )
)
:: 2) PATH 中的 pythonw
if not defined PYTHON_EXE (
    where pythonw.exe >nul 2>&1
    if %errorlevel%==0 (
        for /f "delims=" %%i in ('where pythonw.exe') do (
            if not defined PYTHON_EXE set PYTHON_EXE=%%i
        )
    )
)
:: 3) py launcher（装了 Python 但没加 PATH 时必带）
if not defined PYTHON_EXE (
    where py.exe >nul 2>&1
    if %errorlevel%==0 (
        for /f "delims=" %%i in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do (
            if not defined PYTHON_EXE set PYTHON_EXE=%%i
        )
    )
)
:: 4) 常见安装路径兜底（装了但没加 PATH 的最后保险）
if not defined PYTHON_EXE (
    for %%P in (
        "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
        "C:\Python312\python.exe"
        "C:\Python311\python.exe"
        "C:\Python310\python.exe"
        "C:\Program Files\Python312\python.exe"
        "C:\Program Files\Python311\python.exe"
    ) do (if not defined PYTHON_EXE if exist %%~P set PYTHON_EXE=%%~P)
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

:: Start backend via watchdog（看门狗托管 uvicorn：崩溃/被误杀自动重拉，避免 backend 静默宕机）
:: 控制台流必须重定向到**另一个**文件：backend_watchdog.py 自己用
:: logging.FileHandler 打开 log\backend_watchdog.log；若 '>' 指向同一路径，
:: cmd 会独占句柄导致看门狗 PermissionError [Errno 13] 退出。
echo [*] Starting backend watchdog (auto-restart backend, port 7038)...
tasklist /fi "IMAGENAME eq python.exe" /v 2>nul | findstr /i "BackendWatchdog" >nul 2>&1
if %errorlevel%==0 (
    echo [*] Backend watchdog already running; reusing.
) else (
    :: 清理可能存在的孤儿 backend（旧方式直接启动的 uvicorn），避免看门狗再拉起第二个抢端口
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":7038" ^| findstr "LISTENING" 2^>nul') do (
        taskkill /PID %%a /F >nul 2>&1
    )
    :: 清理 7040/8000 残留实例：不清理会与 7038 双开导致任务双份执行（08-13 main_kpi_sync 事故）
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":7040" ^| findstr "LISTENING" 2^>nul') do (
        taskkill /PID %%a /F >nul 2>&1
    )
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING" 2^>nul') do (
        taskkill /PID %%a /F >nul 2>&1
    )
    start "BackendWatchdog" /MIN cmd /c "chcp 65001 >nul & set CODEBUDDY_SESSION_ID=&set CLAUDE_SESSION_ID=&set CODEBUDDY_SAFE_DELETE_SANDBOX=& "%PYTHON_EXE%" -m backend.backend_watchdog > "%~dp0log\backend_watchdog_console.log" 2>&1"
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
echo         Check log\backend_runtime.log before starting the frontend.
pause
exit /b 1

:backend_ready
echo [OK] Backend is listening on port 7038.

:: Start task worker watchdog（托管 backend.worker：崩溃/被杀后自动重拉，避免 Last 冻结）
:: MY_APP_WORKER_GROUPS=u,n,m：三组 worker 并行消费（u=UME 会话组，n=网管/eFlow 组，m=内务轻任务组）；
:: 组内串行与旧行为一致，组间并行（行为等价并发）。改回单 worker：删除该变量即可。
:: 控制台流必须重定向到**另一个**文件：worker_watchdog.py 自己用
:: logging.FileHandler 打开 log\worker_watchdog.log；若 '>' 指向同一路径，
:: cmd 会独占该文件句柄，看门狗启动时直接 PermissionError [Errno 13] 退出，
:: 结果是 Web 端照常投递队列、却没有任何 worker 消费（任务永远 pending）。
echo [*] Starting task worker watchdog (auto-restart worker, groups=u,n,m)...
start "TaskWorkerWatchdog" /MIN cmd /c "chcp 65001 >nul & set CODEBUDDY_SESSION_ID=&set CLAUDE_SESSION_ID=&set CODEBUDDY_SAFE_DELETE_SANDBOX=& set MY_APP_WORKER_GROUPS=u,n,m& "%PYTHON_EXE%" -m backend.worker_watchdog > "%~dp0log\worker_watchdog_console.log" 2>&1"

:: Start frontend（生产模式：vite preview 托管 dist 构建产物）
:: 说明：dev 模式（npm run dev）直出未打包源码，浏览器内存开销大，易触发标签页
:: Out of Memory 崩溃；改用 vite preview 服务压缩后的 dist（见 vite.config.ts preview）。
:: 注意：改前端源码后需先 npm run build 再启动，否则页面停留在旧构建。
echo [*] Starting frontend preview server (port 7090, serving dist/)...
cd frontend
start "Frontend" /MIN cmd /c "%NPM_CMD% run preview > "%~dp0log\frontend_runtime.log" 2>&1"
cd ..

:: Wait and verify backend
echo [*] Waiting for services to start...
timeout /t 6 /nobreak >nul

:: 检测后端是否存活
netstat -ano | findstr ":7038" | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo [OK] Backend is running on port 7038
) else (
    echo [WARN] Backend may have failed to start! Check log\backend_runtime.log
    echo        Common causes: port conflict, missing dependencies, Python version issue
    type "%~dp0log\backend_runtime.log" 2>nul
)

:: 检测看门狗（worker 管理器）是否存活；看门狗负责保活分组 worker
:: 只看 watchdog PID 文件不够：进程死了 PID 文件仍会残留，导致"假 OK"。
:: 必须同时确认三组 worker 的 PID 文件都已生成，才代表队列真的有消费者。
if exist "%~dp0backend\worker_watchdog.pid" (
    echo [OK] Task worker watchdog is running (auto-restart enabled, groups=u,n,m)
) else (
    echo [WARN] Worker watchdog PID file not found! Check log\worker_watchdog_console.log
)

set /a WCOUNT=0
if exist "%~dp0backend\worker_u.pid" set /a WCOUNT+=1
if exist "%~dp0backend\worker_n.pid" set /a WCOUNT+=1
if exist "%~dp0backend\worker_m.pid" set /a WCOUNT+=1
echo [*] Worker groups up: %WCOUNT% / 3
if %WCOUNT% LSS 3 (
    echo [WARN] Task queue has no full consumer set! Tasks will pile up as pending.
    echo        Check log\worker_runtime.log and log\worker_watchdog.log
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
