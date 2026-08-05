@echo off
REM 包装脚本：由 Windows 任务计划程序（每日 03:15）调用。
REM 使用 venv python 运行可用性脚本，并把输出追加到 run.log 便于排查。
set "PY=D:\01_RPA\.venv\Scripts\python.exe"
set "SCRIPT=D:\01_RPA\Task\RAN\Avalability\ran_kpi_avalability_1day.py"
set "LOG=D:\01_RPA\Task\RAN\Avalability\run.log"

if not exist "%PY%" (
    echo [ERROR] 找不到 python: %PY% >> "%LOG%"
    exit /b 1
)

echo ==== RUN %DATE% %TIME% ==== >> "%LOG%"
"%PY%" "%SCRIPT%" >> "%LOG%" 2>&1
echo ==== EXIT %DATE% %TIME% (code=%ERRORLEVEL%) ==== >> "%LOG%"
