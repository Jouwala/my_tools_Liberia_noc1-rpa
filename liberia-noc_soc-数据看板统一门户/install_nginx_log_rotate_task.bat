@echo off
REM ============================================================
REM  install_nginx_log_rotate_task.bat - register the
REM  "Nginx_LogRotate" scheduled task: once a day, rotate THIS
REM  host's nginx access log.
REM
REM  The log path is whatever rotate_nginx_logs.ps1's -Prefix default is
REM  (D:\01_RPA\nginx-1.28.0\logs\access-<hostname>.log since 2026-10-01,
REM  when nginx was moved off the Y: network share onto the local disk).
REM
REM  Companion of rotate_nginx_logs.ps1. The task is created for
REM  the current user, only while that user is logged on - the same
REM  shape as Portal_EnsureRunning.
REM
REM  A plain double-click is enough: the script re-launches itself
REM  elevated when needed (task creation needs administrator rights).
REM
REM  Uninstall with:
REM     schtasks /delete /tn "Nginx_LogRotate" /f
REM ============================================================
set "BASE=%~dp0"

net session >nul 2>&1
if %errorlevel%==0 goto register

echo Requesting administrator rights - please click "Yes" on the UAC prompt...
powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
exit /b 0

:register
echo ============================================
echo   Registering Nginx_LogRotate ...
echo ============================================
echo   Runs:    powershell -File "%BASE%rotate_nginx_logs.ps1"
echo   Repeat:  every 6 hours (this host writes about 120 MB/day)
echo   Rotates: logs\access-%COMPUTERNAME%.log (zip + prune, 14 days kept)
echo.

schtasks /create /tn "Nginx_LogRotate" /tr "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"%BASE%rotate_nginx_logs.ps1\"" /sc hourly /mo 6 /f
if errorlevel 1 (
    echo [*] Retrying with a simpler command line...
    schtasks /create /tn "Nginx_LogRotate" /tr "powershell.exe -NoProfile -ExecutionPolicy Bypass -File %BASE%rotate_nginx_logs.ps1" /sc hourly /mo 6 /f
)

schtasks /query /tn "Nginx_LogRotate" /fo LIST >nul 2>&1
if errorlevel 1 (
    echo.
    echo [FAIL] Could not register the task. Run this in an elevated Command Prompt:
    echo        schtasks /create /tn "Nginx_LogRotate" /tr "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"%BASE%rotate_nginx_logs.ps1\"" /sc hourly /mo 6 /f
    echo.
    pause >nul
    exit /b 1
)

echo [OK] Nginx_LogRotate is registered.
echo.
echo Dry-run it any time with:
echo   powershell -NoProfile -ExecutionPolicy Bypass -File "%BASE%rotate_nginx_logs.ps1" -DryRun
echo.
echo Remove it with:  schtasks /delete /tn "Nginx_LogRotate" /f
echo.
pause >nul
exit /b 0
