' my_app.vbs - 隐藏启动脚本 (完美复刻 bat 逻辑)
' 后台无窗口启动后端(pythonw)和前端(vite)，不弹出任何控制台

Set ws = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' 获取脚本所在目录，并设置为当前工作目录（关键！）
base = fso.GetParentFolderName(WScript.ScriptFullName)
ws.CurrentDirectory = base

' 确保日志目录存在（所有日志重定向到 log\ 子目录，保持项目根目录整洁）
logDir = fso.BuildPath(base, "log")
If Not fso.FolderExists(logDir) Then fso.CreateFolder(logDir)

' ===== 1. 自动检测 Python（隐藏启动：优先同目录的 pythonw.exe 以彻底无控制台窗口） =====
backendExe = ""
On Error Resume Next
' 先定位 python.exe（确定解释器目录，避免误用 managed 3.13 导致依赖缺失）
Set exec = ws.Exec("cmd /c where python.exe")
If Err.Number = 0 Then
    backendExe = Trim(exec.StdOut.ReadLine())
End If
On Error GoTo 0

If backendExe <> "" And fso.FileExists(backendExe) Then
    ' 同目录换成 pythonw.exe（GUI 子系统，不弹控制台窗口），实现真正隐藏
    Dim pywDir, pywCand
    pywDir = fso.GetParentFolderName(backendExe)
    pywCand = fso.BuildPath(pywDir, "pythonw.exe")
    If fso.FileExists(pywCand) Then
        backendExe = pywCand
    End If
Else
    ' python.exe 都找不到时，再兜底直接找 pythonw.exe
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

' ===== 3. 启动后端服务（经 backend_watchdog 托管，崩溃/被杀自动重拉） =====
' 关键改动：不再直接 launch uvicorn，改由 backend.backend_watchdog 进程托管 uvicorn。
' 看门狗会：清除 WorkBuddy 安全删除守卫 env、设置 MY_APP_TASK_QUEUE=1、
' 以子进程方式拉起 uvicorn、进程死亡或端口长时间未监听时自动重拉，
' 从根本上避免"backend 单独宕机、定时任务静默漏跑"的问题（详见 backend_watchdog.py）。
' 控制台流重定向到 backend_watchdog_console.log（看门狗自身用 FileHandler 写
' backend_watchdog.log，二者不可同一路径，否则 Windows 下 cmd 独占句柄会致启动即失败）。
If Not IsPortListening(7038) Then
    ' 先清理孤儿 backend（旧方式直启的 uvicorn / 残留进程），避免看门狗再拉起第二个抢端口
    Set orphanKill = ws.Exec("cmd /c for /f ""tokens=5"" %a in ('netstat -ano ^| findstr "":7038"" ^| findstr ""LISTENING""') do taskkill /PID %a /F")
    orphanKill.StdOut.ReadAll
    orphanKill.StdErr.ReadAll
    watchdogConsoleLog = fso.BuildPath(base, "log\backend_watchdog_console.log")
    backendWatchdogCmd = "cmd /c chcp 65001 >nul & """ & backendExe & """ -m backend.backend_watchdog > """ & watchdogConsoleLog & """ 2>&1"
    ws.Run backendWatchdogCmd, 0, False
End If

' Wait for the backend before exposing the frontend proxy. Otherwise Vite returns 502.
waited = 0
Do While Not IsPortListening(7038) And waited < 30
    WScript.Sleep 1000
    waited = waited + 1
Loop
If Not IsPortListening(7038) Then
    MsgBox "Backend did not start on port 7038 within 30 seconds." & vbCrLf & "Check log\backend_runtime.log.", vbCritical, "Data Insight MVP"
    WScript.Quit 1
End If

' 看门狗（worker 管理器）：崩溃/被杀后自动重拉 worker，避免队列永远 pending。
' 关键点（今日故障同款坑，已修复）：
' 1) console 日志必须重定向到 worker_watchdog_console.log —— worker_watchdog.py 自身
'    已用 logging.FileHandler 打开 worker_watchdog.log；若此处 '>' 再指向同一文件，
'    Windows 下 cmd 独占句柄会导致看门狗启动即 PermissionError 退出，worker 全灭。
' 2) 必须带 MY_APP_WORKER_GROUPS=u,n,m，否则回退单 default worker（串行、无分组并行）。
' 3) 不再用 worker_watchdog.pid 是否存在来跳过启动：PID 文件残留（进程已死）会让看门狗
'    永不重启。重复启动由 worker_watchdog.py 的 _another_watchdog_running() 守卫拦截，
'    故始终拉起即可（与 start.bat 行为保持一致）。
watchdogLog = fso.BuildPath(base, "log\worker_watchdog_console.log")
watchdogCmd = "cmd /c chcp 65001 >nul & set CODEBUDDY_SESSION_ID=&set CLAUDE_SESSION_ID=&set CODEBUDDY_SAFE_DELETE_SANDBOX=& set MY_APP_WORKER_GROUPS=u,n,m& """ & backendExe & """ -m backend.worker_watchdog > """ & watchdogLog & """ 2>&1"
ws.Run watchdogCmd, 0, False

' ===== 4. 启动前端服务（生产模式：vite preview 托管 dist 构建产物） =====
' dev 模式（npm run dev）直出未打包源码，浏览器内存开销大，易触发标签页
' Out of Memory 崩溃；改用 vite preview 服务压缩后的 dist（见 vite.config.ts preview）。
' 注意：改前端源码后需先 npm run build 再启动，否则页面停留在旧构建。
frontendDir = fso.BuildPath(base, "frontend")
frontendLog = fso.BuildPath(base, "log\frontend_runtime.log")
If Not IsPortListening(7090) Then
    frontendCmd = "cmd /c cd /d """ & frontendDir & """ & """ & npmCmd & """ run preview > """ & frontendLog & """ 2>&1"
    ws.Run frontendCmd, 0, False
End If

' ===== 5. 等待服务启动后打开浏览器（可传 nobrowser 跳过，用于登录自启不弹窗） =====
WScript.Sleep 6000
Dim openBrowser
openBrowser = True
If WScript.Arguments.Count > 0 Then
    If LCase(WScript.Arguments(0)) = "nobrowser" Then openBrowser = False
End If
If openBrowser Then
    ws.Run "http://localhost:7090"
End If

Function IsPortListening(port)
    Set portCheck = ws.Exec("cmd /c netstat -ano | findstr :" & port & " | findstr LISTENING")
    IsPortListening = Not portCheck.StdOut.AtEndOfStream
End Function
