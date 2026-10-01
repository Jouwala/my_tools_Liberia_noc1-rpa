' notify_watchdog_hidden.vbs - hidden wrapper for the WhatsAppKB_Notify_EnsureRunning task
'
' 为什么需要它：计划任务通过 wscript.exe（GUI 子系统）拉起本脚本，本脚本再以
' 窗口样式 0（完全隐藏）运行 autostart-notify.ps1 -Watch。若直接让任务调用
' powershell.exe，每 5 分钟会闪一次黑框 —— 与 nginx_monitor_hidden.vbs /
' start_ensure_hidden.vbs 的处理方式保持一致。
'
' autostart-notify.ps1 -Watch 是「跑一轮就退出」的单次巡检，
' 因此这里用 0（不等待）即可，由任务的 5 分钟周期提供重复性。
'
' 为什么 P1 告警通道要单独设看门狗：
'   2026-10-01 事故的教训是「监控全绿但业务已坏」。推送进程一旦不在，
'   值班群收不到任何 P1 告警，而任务日志可能仍显示成功。故不能只靠开机自启，
'   必须有周期巡检把它拉回来。
'
' 相关：
'   - 巡检脚本：D:\01_RPA\Task\whatsapp-kb-bot\autostart-notify.ps1
'   - 推送进程：D:\01_RPA\Task\whatsapp-kb-bot\src\notify.js
'   - 心跳文件：D:\01_RPA\Task\whatsapp-kb-bot\data\notify_heartbeat.json
'     （my_app 侧 wa_notify_service.is_online() 读同一个文件判在线）

Set ws = CreateObject("WScript.Shell")
dir = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
ws.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & dir & "autostart-notify.ps1"" -Watch", 0, False
