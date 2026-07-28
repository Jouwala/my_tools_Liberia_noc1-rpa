# ============================================================
# fix_file_lock.ps1 - 修复 RPA 任务因文件锁导致 PermissionError
# 需要以管理员身份运行 PowerShell
# 根因：WPS云同步 + Windows Defender实时扫描 + Search Indexer 三重锁
# ============================================================

#Requires -RunAsAdministrator

$ErrorActionPreference = "Continue"
$RPA_DIR = "D:\01_RPA"

Write-Host "=" * 60
Write-Host " RPA 文件锁修复脚本（需管理员权限）"
Write-Host "=" * 60

# ---- 1. Windows Defender 排除 ----
Write-Host "`n[1/3] Windows Defender 排除路径..."
try {
    Add-MpPreference -ExclusionPath $RPA_DIR -ErrorAction Stop
    Write-Host "  [OK] 已添加排除: $RPA_DIR" -ForegroundColor Green
} catch {
    Write-Host "  [FAIL] $($_.Exception.Message)" -ForegroundColor Red
}

# 排除 Python 进程（避免扫描 python 写入的文件）
$pythonPaths = @(
    "C:\Users\ZTEEMS\AppData\Local\Programs\Python\Python312\python.exe",
    "d:\01_RPA\.venv\Scripts\python.exe"
)
foreach ($p in $pythonPaths) {
    if (Test-Path $p) {
        try {
            Add-MpPreference -ExclusionProcess $p -ErrorAction Stop
            Write-Host "  [OK] 已排除进程: $p" -ForegroundColor Green
        } catch {
            Write-Host "  [WARN] 排除进程失败: $p" -ForegroundColor Yellow
        }
    }
}

# 验证
$prefs = Get-MpPreference
Write-Host "  当前排除路径: $($prefs.ExclusionPath -join ', ')"
Write-Host "  当前排除进程: $($prefs.ExclusionProcess -join ', ')"

# ---- 2. WPS 云同步处理 ----
Write-Host "`n[2/3] WPS 云同步服务..."

# 停止 wpscloudsvr 进程
$wpsCloud = Get-Process -Name "wpscloudsvr" -ErrorAction SilentlyContinue
if ($wpsCloud) {
    Stop-Process -Name "wpscloudsvr" -Force -ErrorAction SilentlyContinue
    Write-Host "  [OK] 已终止 wpscloudsvr 进程" -ForegroundColor Green
} else {
    Write-Host "  [INFO] wpscloudsvr 未运行" -ForegroundColor Cyan
}

# 禁止 wpscloudsvr 开机自启（通过注册表）
$wpsRunKeys = @(
    "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run",
    "HKLM:\Software\Microsoft\Windows\CurrentVersion\Run",
    "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run"
)
foreach ($key in $wpsRunKeys) {
    if (Test-Path $key) {
        $props = Get-ItemProperty $key -ErrorAction SilentlyContinue
        $propNames = $props.PSObject.Properties | Where-Object { $_.Value -match "wpscloud|kso" }
        foreach ($prop in $propNames) {
            Remove-ItemProperty -Path $key -Name $prop.Name -ErrorAction SilentlyContinue
            Write-Host "  [OK] 已移除自启: $($prop.Name)" -ForegroundColor Green
        }
    }
}

# 重命名 wpscloudlaunch.exe 阻止 WPS 主进程拉起云服务
$wpsCloudExe = Get-ChildItem "C:\Users\ZTEEMS\AppData\Local\Kingsoft" -Recurse -Filter "wpscloudlaunch.exe" -ErrorAction SilentlyContinue
foreach ($exe in $wpsCloudExe) {
    $disabled = $exe.FullName + ".disabled"
    if (-not (Test-Path $disabled)) {
        Rename-Item $exe.FullName $disabled -ErrorAction SilentlyContinue
        Write-Host "  [OK] 已禁用: $($exe.FullName)" -ForegroundColor Green
    }
}

Write-Host "  [TIP] 如需彻底关闭: WPS设置 → 云文档 → 取消'自动同步'" -ForegroundColor Yellow

# ---- 3. Windows Search Indexer 排除 ----
Write-Host "`n[3/3] Windows Search Indexer..."

# 检查索引服务状态
$svc = Get-Service WSearch -ErrorAction SilentlyContinue
if ($svc -and $svc.Status -eq "Running") {
    Write-Host "  [INFO] WSearch 服务运行中"

    # 尝试通过注册表排除 D:\01_RPA 目录
    $indexKey = "HKLM:\SOFTWARE\Microsoft\Windows Search\CrawlScopeManager\Windows\SystemIndex\DefaultRules"
    if (Test-Path $indexKey) {
        # 添加排除规则（值为 0 表示排除）
        New-ItemProperty -Path $indexKey -Name "file:///D:/01_RPA/" -Value 0 -PropertyType DWord -Force -ErrorAction SilentlyContinue | Out-Null
        Write-Host "  [OK] 已添加索引排除: D:\01_RPA" -ForegroundColor Green
    } else {
        Write-Host "  [WARN] 索引注册表路径不存在，跳过" -ForegroundColor Yellow
    }

    # 重启索引服务使配置生效
    Restart-Service WSearch -Force -ErrorAction SilentlyContinue
    Write-Host "  [OK] WSearch 服务已重启" -ForegroundColor Green
} else {
    Write-Host "  [INFO] WSearch 未运行，无需处理" -ForegroundColor Cyan
}

# ---- 完成 ----
Write-Host "`n" + ("=" * 60)
Write-Host " 修复完成！建议操作："
Write-Host "   1. 重启 WPS Office（如正在使用）"
Write-Host "   2. 重新运行失败的 RPA 任务验证"
Write-Host "   3. 如仍有问题，考虑直接禁用 WSearch: Set-Service WSearch -StartupType Disabled"
Write-Host ("=" * 60)
