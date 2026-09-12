@echo off
REM ============================================================
REM  start_ensure.bat - "Portal_EnsureRunning" scheduled task entry
REM  Runs every 5 minutes (registered by install_ensure_task.bat).
REM
REM  Calls start_hidden.ps1 -Quiet: idempotent, starts only what is
REM  missing (portal dev server 9267 + WhatsApp analysis service 9268)
REM  and writes log\start_hidden_result.txt.
REM
REM  Respects stopped.flag: after stop.bat the task does nothing until
REM  start.bat is run again.
REM
REM  NOTE: do NOT add "chcp 65001" here. The project path contains
REM  non-ASCII characters; with the default system code page the path is
REM  handed to powershell.exe correctly, while switching the console to
REM  UTF-8 can make the -File argument unresolvable.
REM ============================================================
cd /d "%~dp0"

REM Task Scheduler starts with a minimal PATH, so make node/npm reachable.
REM C:\Program Files\nodejs is the system Node (v24), which satisfies the
REM "node >= 23.4.0" requirement of the WhatsApp analysis service.
set "PATH=C:\Program Files\nodejs;%APPDATA%\npm;%PATH%"

"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_hidden.ps1" -Quiet

exit /b 0
