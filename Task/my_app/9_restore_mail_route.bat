@echo off
REM ============================================================
REM 9_restore_mail_route.bat
REM Undo everything done by 1_fix_mail_route_wifi.bat:
REM remove the Exchange host route and restore Wi-Fi auto metric.
REM MUST run as Administrator.
REM ============================================================

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Not running as Administrator.
    echo         Right-click this file and choose "Run as administrator".
    pause
    exit /b 1
)

echo [1/2] Remove persistent host route to 41.202.66.149 ...
route -p delete 41.202.66.149 >nul 2>&1
route delete 41.202.66.149 >nul 2>&1

echo [2/2] Restore automatic metric on Wi-Fi adapter ...
powershell -NoProfile -Command "Set-NetIPInterface -InterfaceAlias 'Wi-Fi' -AutomaticMetric enabled"

echo.
echo Restored. You may also re-apply the LAN default metric by running 1_fix_mail_route_wifi.bat later.
pause
