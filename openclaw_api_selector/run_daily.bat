@echo off
REM 每天由 Windows 任务计划程序调用：运行 OpenClaw API 优选器
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "PYTHON=C:\Users\ZTEEMS\.workbuddy\binaries\python\versions\3.13.12\python.exe"
set "SCRIPT=D:\01_RPA\openclaw_api_selector\api_selector.py"
set "LOG=D:\01_RPA\openclaw_api_selector\scheduler.log"

echo [%date% %time%] === OpenClaw API selector start === >> "%LOG%"
"%PYTHON%" -X utf8 "%SCRIPT%" --parallel 4 --probes 2 --max-models 5 >> "%LOG%" 2>&1
echo [%date% %time%] === end exit=%errorlevel% === >> "%LOG%"
