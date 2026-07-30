' my_app.vbs - 隐藏启动脚本 (完美复刻 bat 逻辑)
' 后台无窗口启动后端(pythonw)和前端(vite)，不弹出任何控制台

Set ws = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' 获取脚本所在目录，并设置为当前工作目录（关键！）
base = fso.GetParentFolderName(WScript.ScriptFullName)
ws.CurrentDirectory = base

' ===== 1. 自动检测 Python (优先 python.exe，便于排查错误) =====
backendExe = ""
On Error Resume Next
' 优先尝试找 python.exe
Set exec = ws.Exec("cmd /c where python.exe")
If Err.Number = 0 Then
    backendExe = Trim(exec.StdOut.ReadLine())
End If
On Error GoTo 0

' 如果找不到 python.exe，再尝试 pythonw.exe
If backendExe = "" Or Not fso.FileExists(backendExe) Then
    On Error Resume Next
    Set exec = ws.Exec("cmd /c where pythonw.exe")
    If Err.Number = 0 Then
        backendExe = Trim(exec.StdOut.ReadLine())
    End If
    On Error GoTo 0
End If

' 如果都找不到，弹窗提示并退出
If backendExe = "" Or Not fso.FileExists(backendExe) Then
    MsgBox "Python not found in PATH!" & vbCrLf & _
           "Please install Python and add to PATH.", vbCritical, "Data Insight MVP"
    WScript.Quit 1
End If

' ===== 2. 自动检测 npm =====
npmCmd = "npm"
On Error Resume Next
Set exec = ws.Exec("cmd /c where npm.cmd")
If Err.Number = 0 Then
    npmCmd = Trim(exec.StdOut.ReadLine())
End If
On Error GoTo 0

' ===== 3. 启动后端服务 =====
' 使用 cmd /c 包裹，确保环境变量正确传递，并将日志重定向
backendLog = fso.BuildPath(base, "backend_runtime.log")
backendCmd = "cmd /c chcp 65001 >nul & """ & backendExe & """ -m uvicorn backend.main:app --host 0.0.0.0 --port 7038 > """ & backendLog & """ 2>&1"
ws.Run backendCmd, 0, False

' ===== 4. 启动前端服务 =====
frontendDir = fso.BuildPath(base, "frontend")
frontendLog = fso.BuildPath(base, "frontend_runtime.log")
' 切换到 frontend 目录并运行 npm run dev
frontendCmd = "cmd /c cd /d """ & frontendDir & """ & """ & npmCmd & """ run dev > """ & frontendLog & """ 2>&1"
ws.Run frontendCmd, 0, False

' ===== 5. 等待服务启动后打开浏览器 =====
WScript.Sleep 6000
ws.Run "http://localhost:7090"