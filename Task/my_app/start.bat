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
echo [*] Starting backend server (port 7038)...
start "Backend" /MIN cmd /c "chcp 65001 >nul & "%PYTHON_EXE%" -m uvicorn backend.main:app --host 0.0.0.0 --port 7038 > "%~dp0backend_runtime.log" 2>&1"

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
