@echo off
rem ============================================================
rem  Daily auth health check wrapper (ASCII only, no CJK here).
rem  Runs the read-only inspector with the COPY portable python, saves a
rem  timestamped report and pushes WeChat only on CRITICAL.
rem
rem  2026-11-11: production moved to D:\01_olbr_portal. The scheduled
rem  task MyApp_AuthHealthCheck has RunLevel=HighestAvailable and cannot
rem  be retargeted by the current user ("Access is denied"), so this
rem  wrapper points at the copy instead. Two fixes applied here:
rem    - ROOT used to be hard-coded D:\01_RPA (inspected the retired stack)
rem    - console cp1252 caused UnicodeEncodeError -> task LastResult=1
rem  Registered as scheduled task: MyApp_AuthHealthCheck (08:30).
rem ============================================================
setlocal
chcp 65001 >nul 2>&1
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "ROOT=D:\01_olbr_portal\Task\my_app"
if not exist "%ROOT%\backend\scripts\auth_health_check.py" set "ROOT=%~dp0"
set "PY=%ROOT%\..\..\runtime\python312\python.exe"
if not exist "%PY%" set "PY=python"
set "LOGDIR=%ROOT%\log"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"

rem --- build YYYYMMDD stamp via PowerShell (locale independent) ---
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set "STAMP=%%i"
rem stdout lands in log\ and is named auth_health_check_YYYYMMDD.log.
rem The scanner skips that filename: the report itself says "yan zheng ma"
rem (captcha) even when the result is OK, and re-scanning it is a false CRITICAL.
set "OUT=%LOGDIR%\auth_health_check_%STAMP%.log"

cd /d "%ROOT%"
"%PY%" "%ROOT%\backend\scripts\auth_health_check.py" --days 1 --save --json --notify >> "%OUT%" 2>&1
set "RC=%ERRORLEVEL%"
echo [%DATE% %TIME%] auth_health_check exit=%RC% >> "%OUT%"
endlocal & exit /b %RC%
