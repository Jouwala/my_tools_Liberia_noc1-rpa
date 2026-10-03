@echo off
REM ============================================================
REM  verify_readiness.bat - 商用就绪度回归（B1-B5）
REM ------------------------------------------------------------
REM  手动跑：  直接双击，或在项目根执行 verify_readiness.bat
REM  接计划任务：见下方 "SCHEDULE" 说明
REM
REM  调用 scripts\verify-readiness.mjs（零依赖，Node 22 原生 fetch）。
REM  全 PASS 退出码 0；有 FAIL 退出码 1（可用于门禁 / 计划任务告警）。
REM
REM  结果同时写入 log\readiness_check.log，便于事后查看。
REM
REM  NOTE: 与 start_ensure.bat 一样，不要加 "chcp 65001" —— 项目路径
REM  含非 ASCII 字符，切到 UTF-8 会让路径解析失败。
REM ============================================================
setlocal
cd /d "%~dp0"

REM 计划任务的 PATH 很精简，显式把 node 加进来
set "PATH=C:\Program Files\nodejs;%APPDATA%\npm;%PATH%"

if not exist "log" mkdir "log"

REM 默认探测本机；如需探测局域网入口，改成 --host 192.168.100.20
set "HOST=%~1"
if "%HOST%"=="" set "HOST=127.0.0.1"

echo [%date% %time%] verify-readiness @ %HOST% >> "log\readiness_check.log"
node "%~dp0scripts\verify-readiness.mjs" --host "%HOST%" >> "log\readiness_check.log" 2>&1
set "RC=%ERRORLEVEL%"
echo [%date% %time%] exit=%RC% >> "log\readiness_check.log"

if %RC%==0 (
  echo [OK] 商用就绪度检查全部通过。
) else (
  echo [WARN] 有检查项未通过，详见 log\readiness_check.log
)
exit /b %RC%

REM ============================================================
REM  SCHEDULE（可选，每天 08:00 自动跑一次并写日志）：
REM    schtasks /create /tn "Portal_ReadinessCheck" ^
REM      /tr "\"%~dp0verify_readiness.bat\" 192.168.100.20" ^
REM      /sc daily /st 08:00 /f
REM  删除：
REM    schtasks /delete /tn "Portal_ReadinessCheck" /f
REM ============================================================
