# 注册 P1 告警推送通道的常驻与看门狗计划任务。
#
# 为什么要有这个脚本（而不是手工敲 Register-ScheduledTask）：
#   本仓库已有 MyApp_AutoStart / MyApp_EnsureRunning / Nginx_EnsureRunning 三个任务，
#   注册方式、主体、隐藏窗口写法都是既定约定。把注册过程固化成脚本，
#   换机/重装时可原样复跑，也便于日后审查「当时到底建了什么」。
#
# 建两个任务：
#   1. WhatsAppKB_Notify_Autostart      —— 登录时拉起一次（开机自启）
#   2. WhatsAppKB_Notify_EnsureRunning  —— 每 5 分钟巡检，挂了/掉线就拉回（看门狗）
#
# 为什么两个都要：2026-10-01 事故的教训是「监控全绿但业务已坏」。
# 只做开机自启的话，进程中途死掉没人知道，值班群会静默收不到 P1 告警。
#
# 与 nginx_monitor / start_ensure 一致：任务调 wscript.exe 跑 .vbs 包装器，
# 由包装器以隐藏窗口拉起 PowerShell —— 直接调 powershell.exe 会每 5 分钟闪黑框。
#
# 用法：
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\register_notify_tasks.ps1
#   # 卸载：
#   Unregister-ScheduledTask -TaskName WhatsAppKB_Notify_Autostart -Confirm:$false
#   Unregister-ScheduledTask -TaskName WhatsAppKB_Notify_EnsureRunning -Confirm:$false
#
# 注意：本脚本保持纯 ASCII（PowerShell 5.1 把无 BOM 的 UTF-8 当 GBK 读）。

$ErrorActionPreference = 'Stop'

$dir     = Split-Path -Parent $MyInvocation.MyCommand.Path
$wrapper = Join-Path $dir 'notify_watchdog_hidden.vbs'

if (-not (Test-Path $wrapper)) {
  throw "wrapper not found: $wrapper"
}

$userId = "$env:USERDOMAIN\$env:USERNAME"

# 以当前用户、最低权限运行：推送进程只需网络与文件访问，不需要管理员。
$principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited

$settings = New-ScheduledTaskSettingsSet `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -StartWhenAvailable `
  -MultipleInstances IgnoreNew `
  -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

# --- 1. 开机（登录）自启 ---------------------------------------------------
$actionAuto = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument ('"{0}"' -f $wrapper)
$triggerAuto = New-ScheduledTaskTrigger -AtLogOn -User $userId

Register-ScheduledTask `
  -TaskName 'WhatsAppKB_Notify_Autostart' `
  -Action $actionAuto -Trigger $triggerAuto `
  -Principal $principal -Settings $settings `
  -Description 'P1 alert push daemon (whatsapp-kb-bot src/notify.js) - start at logon' `
  -Force | Out-Null
Write-Host 'registered: WhatsAppKB_Notify_Autostart'

# --- 2. 每 5 分钟巡检（看门狗）--------------------------------------------
$actionWatch = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument ('"{0}"' -f $wrapper)

# 起算点放在 00:01，与 Nginx_EnsureRunning 一致，避免整点与其它任务挤在一起。
$start = (Get-Date -Hour 0 -Minute 1 -Second 0)
$triggerWatch = New-ScheduledTaskTrigger -Once -At $start `
  -RepetitionInterval (New-TimeSpan -Minutes 5)

Register-ScheduledTask `
  -TaskName 'WhatsAppKB_Notify_EnsureRunning' `
  -Action $actionWatch -Trigger $triggerWatch `
  -Principal $principal -Settings $settings `
  -Description 'P1 alert push daemon watchdog - re-launch every 5 min if down or disconnected' `
  -Force | Out-Null
Write-Host 'registered: WhatsAppKB_Notify_EnsureRunning'

Write-Host ''
Write-Host 'Current state:'
Get-ScheduledTask -TaskName 'WhatsAppKB_Notify_*' |
  Select-Object TaskName, State |
  Format-Table -AutoSize
