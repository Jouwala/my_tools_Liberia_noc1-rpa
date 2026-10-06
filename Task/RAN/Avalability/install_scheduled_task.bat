@echo off
REM ============================================================
REM  安装每日 03:15 定时任务（需「以管理员身份运行」）
REM  右键本文件 -> 以管理员身份运行
REM ============================================================
set "BAT=D:\01_RPA\Task\RAN\Avalability\run_availability.bat"
set "TASK=RAN_KPI_AVAILABILITY_1DAY_API"

echo 创建定时任务: %TASK%  (每日 03:15, 以 SYSTEM 身份运行)
schtasks /create /tn "%TASK%" ^
    /tr "\"%BAT%\"" ^
    /sc daily /st 03:15 ^
    /ru SYSTEM /rl highest /f

if %ERRORLEVEL%==0 (
    echo.
    echo [OK] 定时任务已创建。可在「任务计划程序」中查看 %TASK%
    echo      它会在每天 03:15 自动运行，拉取 RAN UME 前一日可用性数据并上传远程。
) else (
    echo.
    echo [FAIL] 创建失败（错误码 %ERRORLEVEL%）。请确认是以「管理员身份」运行的。
)
pause
