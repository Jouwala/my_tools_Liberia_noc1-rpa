@echo off
REM ============================================================
REM 1_fix_mail_route_wifi.bat
REM Route Orange Exchange (exchmail.orange-cit.ci) via Wi-Fi,
REM keep LAN (192.168.100.254) as the default route for all
REM other traffic. MUST run as Administrator.
REM ============================================================

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Not running as Administrator.
    echo         Right-click this file and choose "Run as administrator".
    pause
    exit /b 1
)

echo.
echo [1/4] Pin Wi-Fi adapter to a high interface metric ...
echo       (so LAN always keeps the default route, even after Wi-Fi DHCP renew)
powershell -NoProfile -Command "Set-NetIPInterface -InterfaceAlias 'Wi-Fi' -AutomaticMetric disabled -InterfaceMetric 5000"
if %errorlevel% neq 0 (
    echo [ERROR] Failed to set Wi-Fi interface metric. Is the adapter name "Wi-Fi"?
    pause
    exit /b 1
)

echo.
echo [2/4] Make sure the LAN default route wins now ...
route change 0.0.0.0 mask 0.0.0.0 192.168.100.254 metric 10 >nul
if %errorlevel% neq 0 (
    echo [ERROR] Failed to change LAN default route metric.
    pause
    exit /b 1
)

echo.
echo [3/4] Add persistent host route for exchmail.orange-cit.ci (41.202.66.149) via Wi-Fi gateway ...
route delete 41.202.66.149 >nul 2>&1
route -p add 41.202.66.149 mask 255.255.255.255 10.237.109.235 metric 10
if %errorlevel% neq 0 (
    echo [ERROR] Failed to add host route. Is Wi-Fi still connected?
    pause
    exit /b 1
)

echo.
echo [4/4] Verify ...
echo --- default route should go via 192.168.100.254 on 192.168.100.20 ---
route print 0.0.0.0 | findstr /C:"0.0.0.0"
echo --- mail server reachability (TcpTestSucceeded should be True) ---
powershell -NoProfile -Command "Test-NetConnection -ComputerName 41.202.66.149 -Port 443 -InformationLevel Quiet"
echo.
echo If Quiet returned True, mail now goes via Wi-Fi and everything else via LAN.
echo Done.
pause
