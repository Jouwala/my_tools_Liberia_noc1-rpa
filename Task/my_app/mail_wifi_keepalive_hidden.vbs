' mail_wifi_keepalive_hidden.vbs - hidden wrapper for the MailWifiKeepAlive scheduled task
'
' 为什么需要它：
'   ping.exe 是控制台程序。任务计划（LogonType=InteractiveToken，即"仅在用户登录时运行"）
'   直接拉起 ping 时，Windows 会为它分配一个新的控制台窗口 —— 表现为每 5 分钟闪一下黑窗。
'   wscript.exe 属 GUI 子系统，用窗口样式 0 拉起 ping，则整条链路无可见窗口。
'   这与 MyApp_EnsureRunning 用 start_ensure_hidden.vbs 的做法保持一致。
'
' 用法（任务计划动作）：
'   wscript.exe D:\01_RPA\Task\my_app\mail_wifi_keepalive_hidden.vbs
'
' 目的不变：每 5 分钟 ping 一次邮件服务器 exchmail.orange-cit.ci (41.202.66.149)，
' 防止 Wi-Fi 因"无 Internet 连接"判定而休眠/掉线，从而保住邮件主机路由。
Set ws = CreateObject("WScript.Shell")
' 0 = 隐藏窗口；False = 不等待 ping 结束（保持任务秒退）
ws.Run "ping.exe -n 1 -w 2000 41.202.66.149", 0, False
