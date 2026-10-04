@echo off
REM ============================================================
REM  stop_nginx.bat - gracefully stop the local nginx
REM
REM  CRITICAL: nginx reads logs\nginx.pid RELATIVE TO ITS OWN
REM  DIRECTORY. Signalling from any other working directory makes
REM  nginx read a stale pid from the wrong place, send the signal
REM  to a process that no longer exists, and print nothing to the
REM  operator - the only trace is "OpenEvent(...) failed" in the
REM  log. That is exactly the 2026-09-28 reload incident
REM  (signal went to pid 91864, real master never got it).
REM  See D:\01_RPA\AGENTS.md section 4 item 6b.
REM
REM  Therefore: cd into this directory first, then signal.
REM
REM  Keep this file ASCII-only (cmd batch parsing).
REM ============================================================
setlocal
cd /d "%~dp0"

echo ============================================
echo   nginx - Stopping...
echo ============================================
echo.

if not exist "%~dp0nginx.exe" (
    echo [ERROR] nginx.exe not found in %~dp0
    echo         Wrong directory? This box uses D:\01_RPA\nginx-1.28.0\
    goto done
)

if not exist "%~dp0logs\nginx.pid" (
    echo [*] No logs\nginx.pid - nginx is not running. Nothing to stop.
    goto check_port
)

REM Guard the pid before signalling: `nginx -s quit` re-reads the pid file
REM itself, and an empty file yields only
REM   [error] invalid PID number "" in "...logs\nginx.pid"
REM which leaves nginx running while looking like it was told to stop.
REM An empty pid file here means the master already exited or is between
REM restarts, so there is nothing to signal.
REM
REM NOTE: clear the variable first (`set /p` leaves it unset on an empty file),
REM and test for empty BEFORE the space-strip - stripping an already-empty
REM variable yields the literal " =" and would defeat the test (2026-10-03).
set "NGINXPID="
set /p NGINXPID=<"%~dp0logs\nginx.pid"
if "%NGINXPID%"=="" (
    echo [WARN] logs\nginx.pid is empty - no master to signal.
    echo        nginx has probably already exited; checking the port instead.
    goto check_port
)
set "NGINXPID=%NGINXPID: =%"

echo [*] Master pid from logs\nginx.pid: %NGINXPID%
echo [*] Sending 'nginx -s quit' from %~dp0 ...

REM -s quit = graceful: finish in-flight requests, then exit.
"%~dp0nginx.exe" -s quit

REM ---- Wait for port 80 to be released ----
REM NOTE: `findstr ":80 "` does NOT match netstat output ("0.0.0.0:80" has no
REM trailing space), which would make this loop exit immediately and report a
REM release that never happened. Use the :Port80Up helper instead.
set /a WAIT=0
:wait_down
call :Port80Up
if %errorlevel% NEQ 0 goto stopped
if %WAIT% GEQ 20 goto stillup
set /a WAIT+=1
ping -n 2 127.0.0.1 >nul
goto wait_down

:stillup
REM Long-lived connections can delay a graceful quit. The pid file is
REM the authoritative liveness signal here.
if exist "%~dp0logs\nginx.pid" (
    echo [WARN] Port 80 still listening after 20s - nginx may be draining keep-alive connections.
    echo        If it must go down now, run stop_nginx.bat again or check %~dp0logs\error.log
) else (
    echo [OK] nginx stopped ^(pid file removed; port may lag on draining connections^).
)
goto check_port

:stopped
echo [OK] nginx stopped - port 80 released.

:check_port
echo.
echo   NOTE: scheduled task Nginx_EnsureRunning probes port 80 every 5 minutes
echo         and will restart nginx automatically. To keep it down, disable
echo         that task first.
echo.
echo   Entry points are now unreachable until nginx is started again.

:done
pause >nul
endlocal
exit /b
goto :eof

REM :Port80Up - return 0 when something is LISTENING on port 80.
REM Requires ":80" then whitespace then LISTENING, so ":8087" and outbound
REM rows whose remote port is 80 do not count. Kept last so execution cannot
REM fall into it; the wait loop reaches it only via `call`.
:Port80Up
netstat -ano | findstr /R /C:":80  *.*LISTENING" >nul 2>&1
exit /b %errorlevel%
