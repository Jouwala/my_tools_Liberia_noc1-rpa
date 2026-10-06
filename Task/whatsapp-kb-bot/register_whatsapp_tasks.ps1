# 注册 WhatsApp 两个常驻进程的「开机自启 + 看门狗」计划任务。
#
# 为什么要有这个脚本（而不是手工敲 Register-ScheduledTask）：
#   本仓库已有 MyApp_AutoStart / MyApp_EnsureRunning / Nginx_EnsureRunning 三个任务，
#   注册方式、主体、隐藏窗口写法都是既定约定。把注册过程固化成脚本，
#   换机/重装时可原样复跑，也便于日后审查「当时到底建了什么」。
#
# 建四个任务，覆盖**两个互相独立**的常驻进程：
#
#   | 进程            | 作用         | 凭据目录            | 自启任务                        | 看门狗任务                        |
#   | --------------- | ------------ | ------------------- | ------------------------------- | --------------------------------- |
#   | src/index.js    | 知识库问答   | data/auth           | WhatsAppKB_Bot_Autostart        | WhatsAppKB_Bot_EnsureRunning      |
#   | src/notify.js   | P1 告警推送  | data/auth-notify    | WhatsAppKB_Notify_Autostart     | WhatsAppKB_Notify_EnsureRunning   |
#
# 两者**必须同时在跑**，互不冲突（凭据目录是分开的，不会互相顶号）。
#
# 为什么每个都要自启 + 看门狗：2026-10-01 事故的教训是「监控全绿但业务已坏」。
# 只做开机自启的话，进程中途死掉没人知道，值班群会静默收不到 P1 告警。
#
# 为什么补上 bot 的两个（2026-10-06）：原先只注册了 notify 的两个任务，
# src/index.js **既没有开机自启也没有看门狗** —— 2026-10-06 15:15 重启后
# 机器人再没起来（notify 因为有任务所以起来了），直到人工发现。这就是那次遗漏。
#
# 与 nginx_monitor / start_ensure 一致：任务调 wscript.exe 跑 .vbs 包装器，
# 由包装器以隐藏窗口拉起 PowerShell —— 直接调 powershell.exe 会每 5 分钟闪黑框。
#
# 用法：
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\register_whatsapp_tasks.ps1
#   # 卸载：
#   Get-ScheduledTask -TaskName 'WhatsAppKB_*' | Unregister-ScheduledTask -Confirm:$false
#
# 注意：本脚本含中文注释，**必须带 BOM 保存**（UTF-8 with BOM）。
# PowerShell 5.1 把「无 BOM 的 UTF-8」当 GBK 读，中文注释会变乱码 —— 这里只是注释，
# 不影响功能，但为了让下一个维护者读得懂，别去掉 BOM。
# （对照：autostart.ps1 / autostart-notify.ps1 是**纯 ASCII**，因为它们要能被
#   计划任务以任意编码环境调起，且历史上踩过 GBK 乱码导致 -match 失效的坑。）

$ErrorActionPreference = 'Stop'

$dir = Split-Path -Parent $MyInvocation.MyCommand.Path

# 两个包装器：分别拉起 autostart.ps1（机器人）与 autostart-notify.ps1（推送）。
$wrappers = @(
  @{ Name = 'Bot';    Script = 'bot_watchdog_hidden.vbs';    Desc = 'knowledge-base Q&A bot (whatsapp-kb-bot src/index.js)' },
  @{ Name = 'Notify'; Script = 'notify_watchdog_hidden.vbs'; Desc = 'P1 alert push daemon (whatsapp-kb-bot src/notify.js)' }
)

foreach ($w in $wrappers) {
  $p = Join-Path $dir $w.Script
  if (-not (Test-Path $p)) { throw "wrapper not found: $p" }
}

$userId = "$env:USERDOMAIN\$env:USERNAME"

# 以当前用户、最低权限运行：这两个进程只需网络与文件访问，不需要管理员。
$principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited

$settings = New-ScheduledTaskSettingsSet `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -StartWhenAvailable `
  -MultipleInstances IgnoreNew `
  -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

foreach ($w in $wrappers) {
  $wrapper = Join-Path $dir $w.Script
  $action = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument ('"{0}"' -f $wrapper)

  # --- 开机（登录）自启 ---------------------------------------------------
  $triggerAuto = New-ScheduledTaskTrigger -AtLogOn -User $userId
  $autoName = "WhatsAppKB_$($w.Name)_Autostart"

  Register-ScheduledTask `
    -TaskName $autoName `
    -Action $action -Trigger $triggerAuto `
    -Principal $principal -Settings $settings `
    -Description ("$($w.Desc) - start at logon") `
    -Force | Out-Null
  Write-Host "registered: $autoName"

  # --- 每 5 分钟巡检（看门狗）--------------------------------------------
  # 起算点放在 00:01，与 Nginx_EnsureRunning 一致，避免整点与其它任务挤在一起。
  $start = (Get-Date -Hour 0 -Minute 1 -Second 0)
  $triggerWatch = New-ScheduledTaskTrigger -Once -At $start `
    -RepetitionInterval (New-TimeSpan -Minutes 5)
  $watchName = "WhatsAppKB_$($w.Name)_EnsureRunning"

  Register-ScheduledTask `
    -TaskName $watchName `
    -Action $action -Trigger $triggerWatch `
    -Principal $principal -Settings $settings `
    -Description ("$($w.Desc) watchdog - re-launch every 5 min if down or disconnected") `
    -Force | Out-Null
  Write-Host "registered: $watchName"
}

Write-Host ''
Write-Host 'Current state:'
Get-ScheduledTask -TaskName 'WhatsAppKB_*' |
  Select-Object TaskName, State |
  Format-Table -AutoSize
