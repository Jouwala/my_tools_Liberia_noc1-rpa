' my_app 隐藏启动脚本
' 后台无窗口启动后端(pythonw)和前端(vite)，不弹出任何控制台
' 停止：双击 stop.bat（会杀死所有 uvicorn / node 进程）

Set ws = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
base = fso.GetParentFolderName(WScript.ScriptFullName)

' ===== 自动检测 Python =====
' 优先从 PATH 查找 pythonw，找不到则用 python
backendExe = ""

On Error Resume Next
Set exec = ws.Exec("where pythonw.exe")
If Err.Number = 0 Then
    backendExe = Trim(exec.StdOut.ReadLine())
End If
On Error GoTo 0

If backendExe = "" Or Not fso.FileExists(backendExe) Then
    On Error Resume Next
    Set exec = ws.Exec("where python.exe")
    If Err.Number = 0 Then
        backendExe = Trim(exec.StdOut.ReadLine())
    End If
    On Error GoTo 0
End If

If backendExe = "" Or Not fso.FileExists(backendExe) Then
    MsgBox "Python not found in PATH!" & vbCrLf & "Please install Python and add to PATH.", vbCritical, "Data Insight MVP"
    WScript.Quit 1
End If

ws.CurrentDirectory = base

' 后端：用 cmd /c 包裹 pythonw，日志输出到文件
backendCmd = "cmd /c """ & backendExe & """ -m uvicorn backend.main:app --host 0.0.0.0 --port 7038 > """ & base & "\backend_runtime.log"" 2>&1"
ws.Run backendCmd, 0, False

' 前端：用 cmd /c 启动 vite（端口 7090，见 vite.config.ts）
frontendCmd = "cmd /c cd /d """ & base & "\frontend"" && npm run dev > """ & base & "\frontend_runtime.log"" 2>&1"
ws.Run frontendCmd, 0, False

' 等待服务启动后打开浏览器
WScript.Sleep 6000
ws.Run "http://localhost:7090"
