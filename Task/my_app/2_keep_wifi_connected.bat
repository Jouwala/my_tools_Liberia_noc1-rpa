@echo off
REM ============================================================
REM 2_keep_wifi_connected.bat
REM Stop Windows from auto-disconnecting Wi-Fi when the hotspot
REM has no public internet (NCSI limited-connectivity recovery),
REM disable USB Wi-Fi power saving, and install a keep-alive job.
REM MUST run as Administrator.
REM ============================================================

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Not running as Administrator.
    echo         Right-click this file and choose "Run as administrator".
    pause
    exit /b 1
)

echo.
echo [1/4] Disable Windows active internet probing (NCSI) ...
echo       (this stops "limited connectivity" auto-disconnect)
reg add "HKLM\SYSTEM\CurrentControlSet\Services\NlaSvc\Parameters\Internet" /v EnableActiveProbing /t REG_DWORD /d 0 /f

echo.
echo [2/4] Disable power saving on Wi-Fi USB adapter ...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp02_wifi_power_fix.ps1"

echo.
echo [3/4] Install keep-alive task: ping mail server via Wi-Fi every 5 min ...
echo       (via wscript hidden wrapper - a bare "ping" action flashes a black
echo        console window every 5 minutes in an interactive session)
schtasks /delete /tn "MailWifiKeepAlive" /f >nul 2>&1
schtasks /create /tn "MailWifiKeepAlive" /tr "wscript.exe \"%~dp0mail_wifi_keepalive_hidden.vbs\"" /sc minute /mo 5 /f

echo.
echo [4/4] Reconnect to the last Wi-Fi profile ...
for /f "delims=" %%s in ('netsh wlan show profiles ^| findstr /C:"All User Profile"') do (
    for /f "tokens=2,* delims=:" %%a in ("%%s") do (
        set "PROFILE=%%b"
    )
)
if defined PROFILE (
    netsh wlan connect name="%PROFILE:~1%"
) else (
    echo [INFO] No saved profile found, connect Wi-Fi manually.
)

echo.
echo Done. Reconnect may take a few seconds.
echo Note: the network icon may now always show "Internet" even without one.
echo To undo everything, run 8_undo_keep_wifi.bat
pause
