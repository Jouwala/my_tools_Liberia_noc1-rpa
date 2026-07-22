@echo off
chcp 65001 >nul 2>&1
title MTN Comsal - Data Insight

:: 使用bat文件自身所在目录（支持任意位置运行）
cd /d "%~dp0"

echo ============================================
echo   MTN Comsal - Data Insight Starting...
echo ============================================
echo.

:: 检查Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.10+ and add to PATH.
    pause
    exit /b 1
)

:: 检查Node.js
node --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js not found. Please install Node.js 18+ and add to PATH.
    pause
    exit /b 1
)

:: 检查前端依赖
if not exist "frontend\node_modules" (
    echo [*] First run detected. Installing frontend dependencies...
    cd frontend
    call npm install
    cd ..
)

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
start "Backend" /MIN python -m uvicorn backend.main:app --host 0.0.0.0 --port 7038

:: Start frontend
echo [*] Starting frontend dev server (port 7090)...
cd frontend
start "Frontend" /MIN cmd /c "npm run dev"
cd ..

:: Wait for services to be ready
echo [*] Waiting for services to start...
timeout /t 5 /nobreak >nul

:: Auto-open browser
echo [*] Opening browser...
start http://localhost:7090

echo.
echo ============================================
echo   MTN Comsal - Data Insight is running!
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
