@echo off
chcp 65001 >nul 2>&1
REM ============================================================
REM 3_hide_mail_wifi_window.bat
REM
REM 背景：2_keep_wifi_connected.bat 注册的 MailWifiKeepAlive 任务，
REM 动作是裸的 `ping -n 1 -w 2000 41.202.66.149`（邮件服务器
REM exchmail.orange-cit.ci）。ping.exe 是控制台程序，而该任务的
REM LogonType=InteractiveToken（仅在用户登录时运行），任务计划会为它
REM 分配一个新的控制台窗口 —— 表现为每 5 分钟闪一个黑窗口
REM （41.202.66.149 不回 ICMP，所以每次要闪满 ~2 秒）。
REM
REM 本脚本把该任务的动作改为 wscript.exe + 隐藏包装器
REM （mail_wifi_keepalive_hidden.vbs，窗口样式 0），与 MyApp_EnsureRunning
REM 用 start_ensure_hidden.vbs 的做法一致：keep-alive 行为不变，窗口消失。
REM
REM 修改计划任务需要管理员权限。MUST run as Administrator.
REM 本脚本可重复执行（幂等）。
REM ============================================================

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Not running as Administrator.
    echo         Right-click this file and choose "Run as administrator".
    pause
    exit /b 1
)

set "TASK=MailWifiKeepAlive"
set "VBS=%~dp0mail_wifi_keepalive_hidden.vbs"

if not exist "%VBS%" (
    echo [ERROR] Hidden wrapper not found: %VBS%
    echo         It ships next to this script; restore it and re-run.
    pause
    exit /b 1
)

echo.
echo [1/3] Point %TASK% at the hidden wscript wrapper ...
schtasks /change /tn "%TASK%" /tr "wscript.exe \"%VBS%\""
if %errorlevel% neq 0 (
    echo [ERROR] schtasks /change failed. Task unchanged.
    pause
    exit /b 1
)

echo.
echo [2/3] Current action should now be the wscript wrapper:
schtasks /query /tn "%TASK%" /v /fo LIST | findstr /C:"Task To Run" /C:"要运行的任务"

echo.
echo [3/3] Run it once to confirm it still fires ...
schtasks /run /tn "%TASK%"

echo.
echo Done. The 5-minute mail-server keep-alive ping now runs fully hidden.
echo If you want to drop the keep-alive entirely instead, run 8_undo_keep_wifi.bat.
pause
