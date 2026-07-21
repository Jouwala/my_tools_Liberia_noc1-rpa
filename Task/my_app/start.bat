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
start "Backend" /MIN python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000

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
