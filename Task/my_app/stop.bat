@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

echo Stopping Data Insight MVP...
echo.

set FOUND=0

:: Stop worker watchdog FIRST（tree-kill 连带 worker 一起停，且不会复活 worker）
if exist "%~dp0backend\worker_watchdog.pid" (
    for /f "usebackq tokens=*" %%a in ("%~dp0backend\worker_watchdog.pid") do (
        taskkill /PID %%a /T /F >nul 2>&1
        echo [*] Killed worker watchdog tree PID=%%a
    )
    del "%~dp0backend\worker_watchdog.pid" >nul 2>&1
    set FOUND=1
)

:: Stop backend watchdog FIRST（tree-kill 连带 uvicorn 一起停，且不会复活 backend）
if exist "%~dp0backend\backend_watchdog.pid" (
    for /f "usebackq tokens=*" %%a in ("%~dp0backend\backend_watchdog.pid") do (
        taskkill /PID %%a /T /F >nul 2>&1
        echo [*] Killed backend watchdog tree PID=%%a
    )
    del "%~dp0backend\backend_watchdog.pid" >nul 2>&1
    set FOUND=1
)

:: 清理分组 worker PID 文件（树杀为强制终止，分组 worker 来不及自删 PID 文件）
for %%f in ("%~dp0backend\worker_*.pid") do del "%%f" >nul 2>&1
:: 兜底清理遗留默认 worker.pid（看门狗模式不使用，但旧实例可能残留）
if exist "%~dp0backend\worker.pid" del "%~dp0backend\worker.pid" >nul 2>&1

:: Stop task worker (Phase 3：兜底，直接按 backend/worker.pid 精确停止；看门狗未启用时仍可用)
if exist "%~dp0backend\worker.pid" (
    for /f "usebackq tokens=*" %%a in ("%~dp0backend\worker.pid") do (
        taskkill /PID %%a /F >nul 2>&1
        echo [*] Killed task worker PID=%%a
    )
    del "%~dp0backend\worker.pid" >nul 2>&1
    set FOUND=1
)

:: Stop backend (port 7038, the actual running instance)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":7038" ^| findstr "LISTENING" 2^>nul') do (
    taskkill /PID %%a /F >nul 2>&1
    echo [*] Killed backend PID=%%a
    set FOUND=1
)

:: Stop backend (port 8000, legacy/duplicate section)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING" 2^>nul') do (
    taskkill /PID %%a /F >nul 2>&1
    echo [*] Killed backend PID=%%a
    set FOUND=1
)

:: Stop backend (port 7040, 调试/残留实例，不清理会与 7038 双开导致任务双份执行)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":7040" ^| findstr "LISTENING" 2^>nul') do (
    taskkill /PID %%a /F >nul 2>&1
    echo [*] Killed backend PID=%%a port-7040
    set FOUND=1
)

:: Stop realtime proxy (port 8787, FMS passthrough for dashboard)
:: 漏杀会导致代理残留、下次启动因端口占用无法拉起新实例。
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8787" ^| findstr "LISTENING" 2^>nul') do (
    taskkill /PID %%a /F >nul 2>&1
    echo [*] Killed realtime proxy PID=%%a port-8787
    set FOUND=1
)

:: Stop frontend (port 7090 / 5173)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":7090" ^| findstr "LISTENING" 2^>nul') do (
    taskkill /PID %%a /F >nul 2>&1
    echo [*] Killed frontend PID=%%a
    set FOUND=1
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5173" ^| findstr "LISTENING" 2^>nul') do (
    taskkill /PID %%a /F >nul 2>&1
    echo [*] Killed frontend PID=%%a
    set FOUND=1
)

:: Also kill any node processes for Vite
taskkill /IM node.exe /F >nul 2>&1

if %FOUND%==0 (
    echo [*] No running instance found.
) else (
    echo [*] Stopped successfully.
)

:: ============ 杀后验证：确认端口真的释放，避免"显示成功实际还在跑" ============
set LEFTOVER=0
for %%p in (7038 7040 7090 5173 8000 8787) do (
    netstat -ano | findstr ":%%p " | findstr "LISTENING" >nul 2>&1
    if !ERRORLEVEL!==0 (
        echo [!!] Port %%p still listening, process not stopped!
        set LEFTOVER=1
    )
)
if %LEFTOVER%==1 (
    echo [!!] Some processes failed to stop. Please check manually:
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":7038 " ^| findstr "LISTENING" 2^>nul') do echo [!!]     taskkill /PID %%a /T /F
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":7090 " ^| findstr "LISTENING" 2^>nul') do echo [!!]     taskkill /PID %%a /T /F
) else (
    echo [OK] Verified: all ports released, services fully stopped.
)
ping -n 2 127.0.0.1 >nul
