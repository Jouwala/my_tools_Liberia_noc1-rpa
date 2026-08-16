@echo off
chcp 65001 >nul 2>&1
title Data Insight MVP

:: 使用 bat 文件自身所在目录（支持任意位置运行）
cd /d "%~dp0"

echo ============================================
echo   Data Insight MVP - Starting...
echo ============================================
echo.

:: ===== 清除停止标记（stop.bat 写的 backend\stopped.flag 会阻止开机自启，手动启动时主动清除） =====
if exist "%~dp0backend\stopped.flag" (
    del "%~dp0backend\stopped.flag" >nul 2>&1
    echo [*] Cleared stopped.flag - autostart re-enabled.
)

:: ===== 启动后端 / 看门狗 / 前端（无窗口：委托 start_hidden.ps1 用 powershell Start-Process -WindowStyle Hidden） =====
:: 不再依赖 wscript/vbs（该环境 wscript 被安全策略拦截，会导致双击启动完全失败）。
echo [*] Starting backend / worker / frontend hidden...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_hidden.ps1"

:: 等待后端起来（否则前端代理 502）
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
