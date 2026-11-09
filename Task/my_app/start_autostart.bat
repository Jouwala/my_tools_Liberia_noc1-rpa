@echo off
REM 2026-11-09: production moved to D:\01_olbr_portal.
REM Scheduled task MyApp_AutoStart is ACL-protected, so forward here.
call "D:\01_olbr_portal\Task\my_app\start_autostart.bat" %*
