@echo off
chcp 65001 >nul 2>&1
title Restart Backend + Task Worker
cd /d "%~dp0"

echo ============================================
echo   Restart backend + task worker watchdog
echo ============================================
echo.

:: ===== 清除停止标记 =====
if exist "%~dp0backend\stopped.flag" (
    del "%~dp0backend\stopped.flag" >nul 2>&1
    echo [*] Cleared stopped.flag - autostart re-enabled.
)

:: ===== 1. 停 worker watchdog（树杀连带 worker） =====
if exist "%~dp0backend\worker_watchdog.pid" (
    for /f "usebackq tokens=*" %%a in ("%~dp0backend\worker_watchdog.pid") do (
        taskkill /PID %%a /T /F >nul 2>&1
        echo [*] Killed worker watchdog tree PID=%%a
    )
    del "%~dp0backend\worker_watchdog.pid" >nul 2>&1
)

:: 兜底清 orphan worker（CIM 比 tasklist CSV 更稳）
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0kill_orphan_workers.ps1"

:: 清分组 worker PID 文件
for %%f in ("%~dp0backend\worker_*.pid") do del "%%f" >nul 2>&1
if exist "%~dp0backend\worker.pid" del "%~dp0backend\worker.pid" >nul 2>&1

:: ===== 2. 停旧 backend watchdog + 清残留端口 =====
if exist "%~dp0backend\backend_watchdog.pid" (
    for /f "usebackq tokens=*" %%a in ("%~dp0backend\backend_watchdog.pid") do (
        taskkill /PID %%a /T /F >nul 2>&1
        echo [*] Killed backend watchdog tree PID=%%a
    )
    del "%~dp0backend\backend_watchdog.pid" >nul 2>&1
)
for %%p in (7038 7040 8000) do (
    for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":%%p" ^| findstr "LISTENING"') do (
        taskkill /PID %%a /F >nul 2>&1
        echo [*] Killed orphan on port %%p PID=%%a
    )
)
ping -n 3 127.0.0.1 >nul

:: ===== 3. 无窗口重启（不再依赖 wscript/vbs） =====
echo [*] Restarting services hidden (no black windows)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_hidden.ps1"

:: ===== 4. 等待并验证 =====
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

echo.
echo ---------- health check ----------
set RESTART_OK=1

netstat -ano 2>nul | findstr ":7038" | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 ( echo [OK]   Backend listening on 7038 ) else ( echo [FAIL] Backend not listening; set RESTART_OK=0 )

if exist "%~dp0backend\worker_watchdog.pid" ( echo [OK]   Watchdog running ) else ( echo [FAIL] Watchdog PID missing; set RESTART_OK=0 )

set /a WCOUNT=0
if exist "%~dp0backend\worker_u.pid" set /a WCOUNT+=1
if exist "%~dp0backend\worker_n.pid" set /a WCOUNT+=1
if exist "%~dp0backend\worker_m.pid" set /a WCOUNT+=1
echo [*]    Worker groups up: %WCOUNT% / 3
if %WCOUNT% LSS 3 ( echo [WARN] Not all worker groups started; set RESTART_OK=0 )
echo ----------------------------------
echo.

if %RESTART_OK%==1 ( echo [DONE] Backend and workers restarted successfully. ) else ( echo [WARN] Restart finished with problems. )
echo.
pause
