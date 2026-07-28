@echo off
chcp 65001 >nul 2>&1
title Data Insight MVP

:: 使用bat文件自身所在目录（支持任意位置运行）
cd /d "%~dp0"

echo ============================================
echo   Data Insight MVP - Starting...
echo ============================================
echo.

:: 获取本机IP地址
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /C:"IPv4"') do (
    for /f "tokens=1" %%b in ("%%a") do (
        set LOCAL_IP=%%b
        goto :found_ip
    )
)
:found_ip

:: Start backend
echo [*] Starting backend server (port 7038)...
start "Backend" "C:\Users\ZTEEMS\AppData\Local\Programs\Python\Python312\pythonw.exe" -m uvicorn backend.main:app --host 0.0.0.0 --port 7038

:: Start frontend
echo [*] Starting frontend dev server (port 7090)...
cd frontend
start "Frontend" /MIN cmd /c "npm run dev"
cd ..

:: Wait for services to be ready
echo [*] Waiting for services to start...
timeout /t 5 /nobreak >nul

:: Auto-open browser to TT&WO Dashboard
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
@echo off
chcp 65001 >nul 2>&1
title Data Insight MVP

:: 使用bat文件自身所在目录（支持任意位置运行）
cd /d "%~dp0"

echo ============================================
echo   Data Insight MVP - Starting...
echo ============================================
echo.

:: Start backend
echo [*] Starting backend server (port 8000)...
start "Backend" "C:\Users\ZTEEMS\AppData\Local\Programs\Python\Python312\pythonw.exe" -m uvicorn backend.main:app --host 0.0.0.0 --port 8000

:: Start frontend
echo [*] Starting frontend dev server (port 5173)...
cd frontend
start "Frontend" /MIN cmd /c "npm run dev"
cd ..

:: Wait for services to be ready
echo [*] Waiting for services to start...
timeout /t 5 /nobreak >nul

:: Auto-open browser to TT&WO Dashboard
echo [*] Opening browser...
start http://localhost:5173

echo.
echo ============================================
echo   Data Insight MVP is running!
echo   Backend:  http://localhost:8000
echo   Frontend: http://localhost:5173
echo ============================================
echo.
echo   Press any key to close this window (services keep running).
echo   Double-click stop.bat to stop all services.
echo.
pause >nul
