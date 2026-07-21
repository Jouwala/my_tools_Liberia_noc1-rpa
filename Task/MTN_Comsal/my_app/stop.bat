@echo off
chcp 65001 >nul 2>&1

echo Stopping MTN Comsal - Data Insight...
echo.

set FOUND=0

:: Stop backend (port 8000)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING" 2^>nul') do (
    taskkill /PID %%a /F >nul 2>&1
    echo [*] Killed backend PID=%%a
    set FOUND=1
)

:: Stop frontend (port 5173)
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
