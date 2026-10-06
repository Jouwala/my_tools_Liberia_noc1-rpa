@echo off
title liberia-noc_soc Portal
:: ---------------------------------------------------------------------------
:: start.bat - start the liberia-noc_soc portal AND its companion WhatsApp
::             local analysis service (the portal page calls it at
::             http://localhost:9268; when it is down the page reports
::             "cannot connect to the local analysis service").
::
:: Keep this file ASCII-only: non-ASCII text breaks cmd batch parsing and can
:: silently corrupt the powershell command line below.
:: ---------------------------------------------------------------------------
cd /d "%~dp0"

echo ============================================
echo   liberia-noc_soc portal - Starting...
echo ============================================
echo.

:: Clear stop marker written by stop.bat (only read by -Quiet runs)
if exist "%~dp0stopped.flag" (
    del "%~dp0stopped.flag" >nul 2>&1
    echo [*] Cleared stopped.flag
)

echo [*] Starting portal (9267) + WhatsApp analysis (9268) hidden...
:: MY_PORTAL_NO_POPUP is set by the desktop-shortcut controller
:: (D:\01_RPA\my_portal_ctl.ps1) when it drives this bat. In that mode we must
:: pass -Quiet, otherwise start_hidden.ps1 opens a modal MessageBox on any
:: warning and BLOCKS until someone clicks it - the dialog can open behind other
:: windows, which made 6-start_portal / 8-start_all look like they never start.
:: The controller clears stopped.flag before calling, so -Quiet's stop-flag
:: check cannot wrongly skip a start the operator asked for.
set "_PSQUIET="
if defined MY_PORTAL_NO_POPUP set "_PSQUIET=-Quiet"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_hidden.ps1" %_PSQUIET%
if errorlevel 1 echo [WARN] Startup reported problems - see log\start_hidden_result.txt

echo.
echo ============================================
echo   Portal:
echo     http://localhost:9267/uniplam/
echo   WhatsApp analysis service:
echo     http://localhost:9268/api/tasks
echo.
echo   Logs:
echo     log\portal_dev.log
echo     log\whatsapp_analysis.log
echo     log\start_hidden_result.txt
echo.
echo   Double-click stop.bat to stop both services.
echo ============================================
echo.
pause >nul
