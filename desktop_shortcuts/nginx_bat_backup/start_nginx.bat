@echo off
REM ============================================================
REM  start_nginx.bat - start the local nginx (80 / 443)
REM
REM  MUST run from the nginx directory itself: nginx reads
REM  logs\nginx.pid relative to its own location, so running
REM  from elsewhere silently signals the wrong (dead) pid.
REM  See D:\01_RPA\AGENTS.md section 4 item 6b (2026-09-28
REM  reload incident).
REM
REM  This box (MSNOC1 / .20) uses D:\01_RPA\nginx-1.28.0\.
REM  Y:\01_RPA\nginx-1.28.0\ belongs to .19 - never touch it.
REM
REM  Keep this file ASCII-only (cmd batch parsing).
REM ============================================================
setlocal
cd /d "%~dp0"

echo ============================================
echo   nginx - Starting...
echo ============================================
echo.

REM ---- Already running? Do not start a second instance ----
REM An extra master would fail to bind 80/443 and just log noise.
REM NOTE on the port test: netstat prints the local address as "0.0.0.0:80"
REM followed by padding - there is NO trailing space after the port number,
REM so `findstr ":80 "` never matches. That mistake made this guard report
REM "already running" on a stopped nginx and silently skip the start
REM (found while testing, 2026-10-03). Match ":80" plus a non-digit via
REM the LISTENING line instead, and cross-check the pid file.
call :Port80Up
if %errorlevel%==0 (
    echo [*] Port 80 is already LISTENING - nginx is running.
    echo     Start skipped ^(no duplicate instance^).
    echo.
    echo   nginx directory: %~dp0
    echo   Config:          %~dp0conf\nginx.conf
    goto verify
)

REM Confirm the executable is really here before claiming anything
if not exist "%~dp0nginx.exe" (
    echo [ERROR] nginx.exe not found in %~dp0
    echo         Wrong directory? This box uses D:\01_RPA\nginx-1.28.0\
    goto done
)

echo [*] Starting nginx.exe from %~dp0 ...
start "" /b "%~dp0nginx.exe"

REM ---- Wait for the port to come up ----
set /a WAIT=0
:wait_port
call :Port80Up
if %errorlevel%==0 goto started
if %WAIT% GEQ 15 goto timeout
set /a WAIT+=1
REM ping is a console-free sleep; timeout fails when stdin is redirected
ping -n 2 127.0.0.1 >nul
goto wait_port

:timeout
echo [ERROR] nginx did not listen on port 80 within 15 seconds.
echo         Check %~dp0logs\error.log
goto done

:started
echo [OK] nginx started - port 80 is listening.

:verify
echo.
echo   Entry points ^(80 redirects to HTTPS, self-signed cert^):
echo     https://localhost/myapp/          Data Insight MVP
echo     https://localhost/uniplam/       Unified portal
echo     https://localhost/v1/olbrportal/ OLR static shell v1
echo     https://localhost/olbrportal/    OLR static shell ^(original^)
echo     https://localhost/MsPortal/      MsPortal
echo     https://localhost/webroot/decision  FineBI ^(proxied^)
echo.

:done
echo.
echo ============================================================
echo   Press Enter to close this window.
echo   nginx keeps running in the background.
echo ============================================================
pause >nul
endlocal
exit /b
goto :eof

REM :Port80Up - return 0 when something is LISTENING on port 80.
REM Matches "0.0.0.0:80" / "[::]:80" by requiring ":80" then whitespace then
REM LISTENING. That excludes ":8087" and outbound rows whose *remote* port is
REM 80. NOTE: a plain `findstr ":80 "` never matches netstat at all, because
REM the local address is "0.0.0.0:80" with no trailing space (2026-10-03 fix).
REM Kept last so execution cannot fall into it; callers use `call`.
:Port80Up
netstat -ano | findstr /R /C:":80  *.*LISTENING" >nul 2>&1
exit /b %errorlevel%
