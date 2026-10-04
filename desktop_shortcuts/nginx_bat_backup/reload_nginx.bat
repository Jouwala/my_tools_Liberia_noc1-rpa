@echo off
REM ============================================================
REM  reload_nginx.bat - validate config, then smoothly reload
REM
REM  Two hard rules, both learned from real incidents:
REM
REM  1) ALWAYS run `nginx -t` first. A reload with a broken config
REM     leaves the master running the OLD config, but every later
REM     restart fails - and if the process dies meanwhile there is
REM     nothing to fall back to. Verify, then reload.
REM
REM  2) Reload MUST be issued from the nginx directory itself.
REM     nginx reads logs\nginx.pid relative to its own location;
REM     from elsewhere it reads a stale pid and the signal vanishes
REM     silently ("OpenEvent(...) failed" in the log only).
REM     See D:\01_RPA\AGENTS.md section 4 item 6b.
REM
REM  Keep this file ASCII-only (cmd batch parsing).
REM ============================================================
REM delayedexpansion: %NEWPID% is read *inside* an if block, so it must
REM be expanded at run time (!NEWPID!) - %NEWPID% would expand at parse
REM time, before set /p ever runs, and compare as empty.
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================
echo   nginx - Reload ^(validate first^)
echo ============================================
echo.

if not exist "%~dp0nginx.exe" (
    echo [ERROR] nginx.exe not found in %~dp0
    echo         Wrong directory? This box uses D:\01_RPA\nginx-1.28.0\
    goto done
)

REM ---- Step 1: syntax test. Reload only if this passes ----
echo [*] Step 1/2 - validating config: nginx -t
echo.
"%~dp0nginx.exe" -t
set TESTRC=%errorlevel%
echo.

if %TESTRC% NEQ 0 (
    echo [ABORT] Config test FAILED ^(exit %TESTRC%^) - reload NOT performed.
    echo         nginx keeps running the previous, known-good config.
    echo         Fix the error above, most likely in:
    echo           %~dp0conf\nginx.conf
    echo         Diff against a recent snapshot to find the change:
    echo           dir /o-d %~dp0conf\nginx.conf.bak*
    goto done
)

echo [OK] Config syntax is valid.

REM ---- Step 2: is it even running? ----
if not exist "%~dp0logs\nginx.pid" (
    echo [WARN] No logs\nginx.pid - nginx is not running, so there is nothing to reload.
    echo        Use start_nginx.bat to start it instead.
    goto done
)

REM Guard the pid value before using it. nginx's -s reload re-reads the pid
REM file itself; handing it an EMPTY file makes it fail with
REM   [error] invalid PID number "" in "...logs\nginx.pid"
REM and - worse - that error is the *only* trace (observed 2026-10-03), so the
REM operator sees a "reload" that silently did nothing at all.
REM An empty pid file also means the master is gone or still shutting down, in
REM which case reload is the wrong action and start is the right one.
REM
REM NOTE: `set /p` leaves the variable UNSET when the file is empty, so clear
REM it first. Order matters: test for empty BEFORE the space-strip, because
REM `set "V=%V: =%"` applied to an already-empty V yields the literal " ="
REM (verified 2026-10-03), which would defeat the emptiness test below.
set "NGINXPID="
set /p NGINXPID=<"%~dp0logs\nginx.pid"
if "%NGINXPID%"=="" (
    echo [ABORT] logs\nginx.pid is empty - refusing to reload.
    echo         An empty pid file means nginx is not running, or its pid file
    echo         was removed while the process was still shutting down.
    echo         Use start_nginx.bat to restart it instead.
    goto done
)
REM Now strip spaces and require pure digits.
set "NGINXPID=%NGINXPID: =%"
echo %NGINXPID%| findstr /R /C:"^[0-9][0-9]*$" >nul 2>&1
if errorlevel 1 (
    echo [ABORT] logs\nginx.pid does not contain a plain number: "%NGINXPID%"
    echo         Refusing to reload. Inspect: type "%~dp0logs\nginx.pid"
    goto done
)

echo [*] Step 2/2 - reloading master pid %NGINXPID% from %~dp0 ...
"%~dp0nginx.exe" -s reload

REM ---- Verify the master actually took the signal ----
REM A graceful reload keeps the same master pid. If the pid file still
REM holds the same value AND the port still listens, the reload landed.
REM NOTE: `findstr ":80 "` never matches netstat ("0.0.0.0:80" has no
REM trailing space) - use the :Port80Up helper (see start_nginx.bat).
ping -n 2 127.0.0.1 >nul
call :Port80Up
if %errorlevel% NEQ 0 (
    echo [FAIL] Port 80 is not listening after reload - nginx may have died.
    echo        Check %~dp0logs\error.log and start_nginx.bat
    goto done
)

if exist "%~dp0logs\nginx.pid" (
    set /p NEWPID=<"%~dp0logs\nginx.pid"
    if "!NEWPID!"=="%NGINXPID%" (
        echo [OK] Reload succeeded - master pid %NGINXPID% still serving on port 80.
    ) else (
        echo [OK] Reload succeeded - master pid changed %NGINXPID% -^> !NEWPID! ^(port 80 up^).
    )
) else (
    echo [OK] Reload completed - port 80 is listening.
)

echo.
echo   New config is live. Verify the site if you changed a proxy target.

:done
pause >nul
endlocal
exit /b
goto :eof

REM :Port80Up - return 0 when something is LISTENING on port 80.
REM Kept at the very end so it can never be fallen into; callers use `call`.
REM Requires ":80" then whitespace then LISTENING, which excludes ":8087"
REM and outbound rows whose *remote* port happens to be 80.
:Port80Up
netstat -ano | findstr /R /C:":80  *.*LISTENING" >nul 2>&1
exit /b %errorlevel%
