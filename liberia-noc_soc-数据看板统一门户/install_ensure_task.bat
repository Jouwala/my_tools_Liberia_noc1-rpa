@echo off
REM ============================================================
REM  install_ensure_task.bat - register the "Portal_EnsureRunning"
REM  scheduled task: every 5 minutes, as the current user, only while
REM  that user is logged on. The task keeps the portal (9267) and the
REM  WhatsApp analysis service (9268) alive.
REM
REM  A plain double-click is enough: the script re-launches itself
REM  elevated when needed (task creation needs administrator rights).
REM
REM  Uninstall with:
REM     schtasks /delete /tn "Portal_EnsureRunning" /f
REM ============================================================
set "BASE=%~dp0"

net session >nul 2>&1
if %errorlevel%==0 goto register

echo Requesting administrator rights - please click "Yes" on the UAC prompt...
powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
exit /b 0

:register
echo ============================================
echo   Registering Portal_EnsureRunning ...
echo ============================================
echo   Runs:    wscript.exe "%BASE%start_ensure_hidden.vbs"
echo            -^> start_ensure.bat -^> start_hidden.ps1 -Quiet
echo   Repeat:  every 5 minutes (while you are logged on)
echo.

REM The task target is the VBS wrapper, not the .bat: it runs without a console
REM window, so the 5-minute check never flashes a black CMD window.
schtasks /create /tn "Portal_EnsureRunning" /tr "wscript.exe \"%BASE%start_ensure_hidden.vbs\"" /sc minute /mo 5 /f
if errorlevel 1 (
    echo [*] Retrying with a simpler command line...
    schtasks /create /tn "Portal_EnsureRunning" /tr "wscript.exe %BASE%start_ensure_hidden.vbs" /sc minute /mo 5 /f
)

schtasks /query /tn "Portal_EnsureRunning" /fo LIST >nul 2>&1
if errorlevel 1 (
    echo.
    echo [FAIL] Could not register the task. Run this in an elevated Command Prompt:
    echo        schtasks /create /tn "Portal_EnsureRunning" /tr "wscript.exe %BASE%start_ensure_hidden.vbs" /sc minute /mo 5 /f
    echo.
    pause >nul
    exit /b 1
)

echo [OK] Portal_EnsureRunning is registered.
echo.
echo Running it once now as a self-test...
schtasks /run /tn "Portal_EnsureRunning"
echo.
echo   In ~10 seconds, log\start_hidden_result.txt should have a fresh timestamp.
echo   If it does not, run:  schtasks /query /tn "Portal_EnsureRunning" /v /fo LIST
echo.
echo   Portal 9267 + WhatsApp analysis 9268 are now checked every 5 minutes.
echo   The task stays silent after stop.bat until you run start.bat again.
echo   Remove it with:  schtasks /delete /tn "Portal_EnsureRunning" /f
echo.
pause >nul
exit /b 0
