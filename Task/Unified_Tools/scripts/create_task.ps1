# 创建定时任务脚本
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-ExecutionPolicy Bypass -File C:\FineBI6.0\webapps\Python\Unified_Tools\scripts\check_data_update.ps1'
$trigger1 = New-ScheduledTaskTrigger -Daily -At '07:00'
$trigger2 = New-ScheduledTaskTrigger -Daily -At '17:00'
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

# 先删除已存在的任务（如果有）
Unregister-ScheduledTask -TaskName 'UnifiedTools_DataUpdate' -Confirm:$false -ErrorAction SilentlyContinue

# 注册任务
Register-ScheduledTask -TaskName 'UnifiedTools_DataUpdate' -Action $action -Trigger $trigger1,$trigger2 -Settings $settings -Description '检查 Unified_Tools data 文件更新并发送邮件'

Write-Host "定时任务创建成功！"
Write-Host "任务: UnifiedTools_DataUpdate"
Write-Host "执行时间: 每天 07:00 和 17:00"
Write-Host "脚本路径: C:\FineBI6.0\webapps\Python\Unified_Tools\scripts\check_data_update.ps1"

# 显示任务状态
Get-ScheduledTask -TaskName 'UnifiedTools_DataUpdate' | Select-Object TaskName, State
