' my_app 无窗口启动器
' 双击本文件即可在后台启动后端(pythonw)与前端(vite)，桌面不出现任何窗口。
' 停止：运行 stop.bat（或在任务管理器结束 uvicorn / node 进程）。

Set ws = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
base = fso.GetParentFolderName(WScript.ScriptFullName)

' 后端必须显式指定解释器绝对路径：
' 系统 PATH 里的 pythonw 会优先命中未安装 uvicorn 的 WorkBuddy 托管 Python 3.13.12，
' 导致后端静默启动失败（pythonw 无控制台，错误不可见）。
' 这里固定用已安装 uvicorn 的 Python312 解释器。
backendExe = "C:\Users\ZTEEMS\AppData\Local\Programs\Python\Python312\pythonw.exe"

ws.CurrentDirectory = base

' 后端：直接用 cmd /c 拉起 pythonw（无 start）。
' pythonw 继承 cmd 的真实日志文件句柄，uvicorn 日志正常落盘；
' ws.Run(..., False) 启动后脚本立即返回，进程独立存活（前端 vite 用同样方式已验证可常驻）。
backendCmd = "cmd /c " & backendExe & " -m uvicorn backend.main:app --host 0.0.0.0 --port 7038 > " & base & "\backend_runtime.log 2>&1"
ws.Run backendCmd, 0, False

' 前端：隐藏 cmd 窗口跑 vite（实际端口 7090，见 vite.config.ts）。
' npm 有真实 stdout，> 重定向到日志文件便于排查。
frontendCmd = "cmd /c cd /d " & base & "\frontend && npm run dev > " & base & "\frontend_runtime.log 2>&1"
ws.Run frontendCmd, 0, False

' 等待服务起来后自动打开浏览器
WScript.Sleep 6000
ws.Run "http://localhost:7090"
