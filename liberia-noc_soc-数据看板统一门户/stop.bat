@echo off
title liberia-noc_soc Portal - stop
:: ---------------------------------------------------------------------------
:: stop.bat - stop the liberia-noc_soc portal AND its companion WhatsApp local
::            analysis service (ports 9267 and 9268).
::
:: The real work is in stop_services.ps1 (process tree handling); this file is
:: only the double-click entry point. Keep it ASCII-only.
:: ---------------------------------------------------------------------------
cd /d "%~dp0"

echo ============================================
echo   Stopping liberia-noc_soc portal + WhatsApp analysis...
echo ============================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop_services.ps1"
if errorlevel 1 (
    echo.
    echo [WARN] Some processes could not be stopped - see log\stop_result.txt
)

echo.
echo   Detail: log\stop_result.txt
echo   Double-click start.bat to start both services again.
echo.
pause >nul
