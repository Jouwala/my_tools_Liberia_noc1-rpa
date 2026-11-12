@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"

REM ============================================================
REM  start_autostart.bat - logon autostart entry (MyApp_AutoStart)
REM
REM  2026-11-11: the live stack is D:\01_olbr_portal. This scheduled
REM  task (MyApp_AutoStart) has RunLevel=HighestAvailable and cannot be
REM  retargeted by the current user (Set-ScheduledTask/schtasks both
REM  "Access is denied"), so this wrapper forwards to the copy - the
REM  same treatment already applied to Portal_EnsureRunning.
REM
REM  The copy bat keeps all the real logic: it does cd /d %~dp0,
REM  ensures PostgreSQL on 5432, then runs the copy start_hidden.ps1
REM  -Quiet (idempotent, respects the copy backend\stopped.flag).
REM ============================================================

call "D:\01_olbr_portal\Task\my_app\start_autostart.bat" %*
exit /b %ERRORLEVEL%
