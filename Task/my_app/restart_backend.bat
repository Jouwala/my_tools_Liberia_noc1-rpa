@echo off
chcp 65001 >nul 2>&1
cd /d "D:\01_RPA\Task\my_app"
start "Backend" /MIN cmd /c "chcp 65001 >nul & C:\Users\ZTEEMS\AppData\Local\Programs\Python\Python312\python.exe -m uvicorn backend.main:app --host 0.0.0.0 --port 7038 > D:\01_RPA\Task\my_app\backend_runtime.log 2>&1"
