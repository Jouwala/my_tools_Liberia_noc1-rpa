@echo off
REM 注册「每天 03:00 自动优选 OpenClaw API」的 Windows 任务计划程序任务。
REM 若提示权限不足，请以「管理员身份」运行本文件。
set "TASKNAME=OpenClawApiSelector"
set "RUNNER=D:\01_RPA\openclaw_api_selector\run_daily.bat"

schtasks /Create /TN "%TASKNAME%" /TR "%RUNNER%" /SC DAILY /ST 03:00 /F
if "%errorlevel%"=="0" (
  echo [OK] 已创建每日任务：%TASKNAME% （每天 03:00 运行）
  echo      手动立即运行一次：schtasks /Run /TN "%TASKNAME%"
  echo      删除任务：schtasks /Delete /TN "%TASKNAME%" /F
) else (
  echo [FAIL] 创建失败（可能需要管理员权限）。请右键「以管理员身份运行」本文件。
)
