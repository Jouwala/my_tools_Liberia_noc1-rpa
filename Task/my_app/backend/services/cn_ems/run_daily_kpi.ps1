# ============================================================
# run_daily_kpi.ps1 - 每日 KPI 定时抓取 (Windows 计划任务入口)
#
# 功能: 取前一个 GMT 完整日的原始测量文件, 按模板生成 CSV 到 csv_out\
# 调度: 每天 08:10 本机时间 (无论本机是 GMT 还是 GMT+8, 均已过 GMT 零点,
#        前一天的测量文件已齐全)
# 手动测试: powershell -File run_daily_kpi.ps1 -PyArgs --reuse
# ============================================================
param([string[]]$PyArgs = @())

$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $dir
$env:PYTHONIOENCODING = "utf-8"

$logDir = Join-Path $dir "logs"
New-Item $logDir -ItemType Directory -Force | Out-Null
$log = Join-Path $logDir ("daily_{0:yyyyMMdd}.log" -f (Get-Date))

"=== EMS KPI daily run @ $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===" |
    Out-File $log -Encoding utf8 -Append

# 用 Start-Process 重定向, 避免 PS5 stderr 包装噪音与 UTF-16 日志乱码
$tmpOut = [System.IO.Path]::GetTempFileName()
$tmpErr = [System.IO.Path]::GetTempFileName()
try {
    $p = Start-Process -FilePath "python" `
        -ArgumentList (@("ems_kpi_query.py", "--mode", "daily") + $PyArgs) `
        -WorkingDirectory $dir -NoNewWindow -Wait -PassThru `
        -RedirectStandardOutput $tmpOut -RedirectStandardError $tmpErr
    Get-Content $tmpOut -Encoding UTF8 | Out-File $log -Encoding utf8 -Append
    $errText = (Get-Content $tmpErr -Encoding UTF8 | Out-String).Trim()
    if ($errText) { $errText | Out-File $log -Encoding utf8 -Append }
    "=== exit code: $($p.ExitCode) @ $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===" |
        Out-File $log -Encoding utf8 -Append
    exit $p.ExitCode
} finally {
    Remove-Item $tmpOut, $tmpErr -Force -ErrorAction SilentlyContinue
    # 清理 30 天前的旧日志
    Get-ChildItem $logDir -Filter "daily_*.log" -File |
        Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } |
        Remove-Item -Force -ErrorAction SilentlyContinue
}
