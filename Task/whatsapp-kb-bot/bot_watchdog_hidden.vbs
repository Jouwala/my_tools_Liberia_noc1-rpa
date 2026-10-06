' bot_watchdog_hidden.vbs - hidden wrapper for the WhatsAppKB_Bot_* tasks
'
' 为什么需要它：计划任务通过 wscript.exe（GUI 子系统）拉起本脚本，本脚本再以
' 窗口样式 0（完全隐藏）运行 autostart.ps1 -Watch。若直接让任务调用
' powershell.exe，每 5 分钟会闪一次黑框 —— 与 notify_watchdog_hidden.vbs /
' nginx_monitor_hidden.vbs / start_ensure_hidden.vbs 的处理方式保持一致。
'
' autostart.ps1 -Watch 是「跑一轮就退出」的单次巡检，
' 因此这里用 0（不等待）即可，由任务的 5 分钟周期提供重复性。
'
' 为什么机器人也需要看门狗（2026-10-06）：此前只给 notify.js 建了任务，
' src/index.js 既没有开机自启也没有看门狗 —— 2026-10-06 15:15 重启后机器人
' 一直没有起来，直到人工发现。它与 notify.js 使用**不同的凭据目录**
' （data/auth vs data/auth-notify），两者应当同时在跑，不是二选一。
'
' 相关：
'   - 巡检脚本：D:\01_RPA\Task\whatsapp-kb-bot\autostart.ps1
'   - 机器人进程：D:\01_RPA\Task\whatsapp-kb-bot\src\index.js
'   - 心跳文件：D:\01_RPA\Task\whatsapp-kb-bot\data\bot_heartbeat.json
'     （看门狗据它判断「活着且已连接」，而不是靠扫命令行）

Set ws = CreateObject("WScript.Shell")
dir = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
ws.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & dir & "autostart.ps1"" -Watch", 0, False
