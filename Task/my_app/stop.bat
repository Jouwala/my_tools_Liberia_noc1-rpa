@echo off
chcp 65001 >nul 2>&1

echo Stopping Data Insight MVP...
echo.

set FOUND=0

:: Stop task worker (Phase 3：通过 backend/worker.pid 精确停止)
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
    echo [*] Killed backend PID=%%a (port 7040)
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
ping -n 2 127.0.0.1 >nul
