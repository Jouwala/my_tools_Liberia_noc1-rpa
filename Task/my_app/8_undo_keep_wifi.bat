@echo off
REM ============================================================
REM 8_undo_keep_wifi.bat
REM Revert everything done by 2_keep_wifi_connected.bat.
REM MUST run as Administrator.
REM ============================================================

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Not running as Administrator.
    echo         Right-click this file and choose "Run as administrator".
    pause
    exit /b 1
)

echo [1/3] Re-enable Windows active internet probing (NCSI) ...
reg add "HKLM\SYSTEM\CurrentControlSet\Services\NlaSvc\Parameters\Internet" /v EnableActiveProbing /t REG_DWORD /d 1 /f

echo [2/3] Restore adapter power saving ...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp02_wifi_power_fix.ps1" -Restore

echo [3/3] Remove keep-alive scheduled task ...
schtasks /delete /tn "MailWifiKeepAlive" /f

echo.
echo Reverted.
pause
