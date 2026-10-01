' nginx_monitor_hidden.vbs - hidden wrapper for the Nginx_EnsureRunning task
'
' 为什么需要它：计划任务通过 wscript.exe（GUI 子系统）拉起本脚本，本脚本再以
' 窗口样式 0（完全隐藏）运行 nginx_monitor.ps1。若直接让任务调用 powershell.exe，
' 每 5 分钟会闪一次黑框 —— 与 MyApp_EnsureRunning 的处理方式保持一致
' （参见 D:\01_RPA\Task\my_app\start_ensure_hidden.vbs）。
'
' nginx_monitor.ps1 是「跑一轮就退出」的单次巡检（Version 3 起），
' 因此这里用 0（不等待）即可，由任务的 5 分钟周期提供重复性。
'
' 相关：
'   - 巡检脚本：同目录 nginx_monitor.ps1
'   - 巡检日志：D:\01_RPA\Task\nginx_monitor.log
'   - 生效 nginx：D:\01_RPA\nginx-1.28.0\（本地盘，2026-10-01 从 Y: 网络映射搬来）

Set ws = CreateObject("WScript.Shell")
dir = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
ws.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & dir & "nginx_monitor.ps1""", 0, False
