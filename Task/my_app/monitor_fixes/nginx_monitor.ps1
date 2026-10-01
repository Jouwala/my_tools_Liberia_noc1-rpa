# Nginx Service Monitor - Fixed Version 3 (2026-09-29)
#
# 本脚本由计划任务 "Nginx_EnsureRunning" 每 5 分钟拉起一次，**跑一轮就退出**。
# 不是常驻循环 —— 见下方「单次巡检」说明。
#
# 修复历史：
#   Version 1 → 2：
#     1) 删除 PowerShell 不支持的 goto（原版本重启代码永远不会执行）
#     2) 探活地址从 127.0.0.1 改为实际服务地址 192.168.100.19
#     3) 用 nginx -s stop 优雅停止，只有残留进程才强杀
#     4) 杀进程范围收窄到 NginxDir，避免误杀其他 nginx
#     5) 重启后验证端口恢复
#
#   Version 2 → 3（2026-09-29 双目录事故后修正）：
#     6) **路径修正**：NginxExe/NginxDir 原指向 E:\01_RPA\nginx-1.28.0（该盘号
#        不存在）。生效目录是 Y:\01_RPA\nginx-1.28.0\（网络映射 \\192.168.100.19\e）。
#        原路径不仅让 Test-Path 永假，还让 Get-NginxProcess 的
#        "ExecutablePath -like E:\..." 过滤永远匹配不到真正的进程 —— 即使脚本
#        在跑，重启逻辑也是死的。
#     7) **探活地址改为 127.0.0.1**：原来探 192.168.100.19（另一台机器）的 80，
#        网络抖动会被误判成 nginx 故障。本机就是 nginx 所在机器，探本机即可。
#     8) **单次巡检**：原 while ($true) 常驻循环不适合被计划任务反复拉起
#        （每次拉起都会多一个永不退出的进程）。改为跑一轮就退出，由计划任务
#        的 5 分钟周期提供重复性；跨轮的「连续失败」状态用 StatePath 落盘。
#     9) **Y 盘可达性防御**：nginx 跑在网络映射盘上。映射失效时**只告警、不重启**
#        —— 否则会在盘不可达时反复发 -s stop、把日志刷成噪声，且无法拉起。
#    10) 进程过滤保留 NginxDir 前缀，但把实际 ExecutablePath 记入日志，
#        便于将来盘符再变时快速定位。
#
#   Version 3 → 4（2026-10-01 搬离网络映射盘）：
#    11) **nginx 从 Y:（\\192.168.100.19\e 网络映射）搬到本地盘 D:**
#        NginxExe/NginxDir 由 Y:\01_RPA\nginx-1.28.0 改为 D:\01_RPA\nginx-1.28.0。
#        起因：2026-09-30 21:56~22:15 nginx 猝死，error.log 无 crash 痕迹，判定为
#        SMB 网络盘 I/O 阻塞（临时文件与日志原先都写在网络盘上）。
#        搬移方式为**复制**而非移动 —— Y: 上那份 .19 也在用，必须保持原样。
#        搬移后 Test-NginxTreeAvailable 的「网络盘专项防御」不再触发（本地盘），
#        保留该分支作为通用的「程序目录可达性」检查。
#        ⚠ 改本脚本路径时必须**同步改** rotate_nginx_logs.ps1 的 -Prefix 默认值，
#        否则日志轮转会去轮转 Y: 上的旧目录。
#
# 设计约束：
#   - 探活用 TCP 连接而非 HTTP 请求：/api/* 因后端未起而 502 时 nginx 本身是
#     健康的，不该被重启。只看端口是否在听。
#   - 不碰 7038/7090/9267/26738/8787 等上游服务：它们各有自己的 ensure 任务。
#   - 杀进程只在 $NginxDir 范围内，绝不波及别的 nginx 实例（Version 2 起的原意）。
#
# 相关文件：
#   - 生效配置：D:\01_RPA\nginx-1.28.0\conf\nginx.conf
#   - 监控日志：D:\01_RPA\Task\nginx_monitor.log
#   - 隔离说明：D:\01_RPA\_quarantine_20260929_nginx_dup\README.md

param(
    [string]$NginxExe = "D:\01_RPA\nginx-1.28.0\nginx.exe",
    [string]$NginxDir = "D:\01_RPA\nginx-1.28.0",
    [string]$HostName = "127.0.0.1",
    [int]$NginxPort = 80,
    [int]$ConnectTimeoutMs = 5000,
    [int]$ReadyTimeoutSeconds = 60,
    # 连续多少轮探测失败才认定「真的挂了」并重启。配合 5 分钟周期，
    # 默认 2 表示连续 2 轮（约 10 分钟）都失败才动手，避免瞬时抖动触发重启。
    [int]$FailThreshold = 2,
    [string]$LogPath = "D:\01_RPA\Task\nginx_monitor.log",
    [string]$StatePath = "D:\01_RPA\Task\nginx_monitor.state"
)

$ErrorActionPreference = 'Continue'

# ---------------- 日志 ----------------
$logDir = Split-Path -Parent $LogPath
if ($logDir -and -not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }

function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] [$Level] $Message"
    Add-Content -Path $LogPath -Value $line -Encoding UTF8
    Write-Host $line
}

# ---------------- 跨轮状态（连续失败计数） ----------------
function Get-FailCount {
    if (Test-Path $StatePath) {
        $raw = (Get-Content $StatePath -Raw -ErrorAction SilentlyContinue)
        $n = 0
        if ([int]::TryParse($raw.Trim(), [ref]$n)) { return $n }
    }
    return 0
}

function Set-FailCount {
    param([int]$Count)
    Set-Content -Path $StatePath -Value $Count -Encoding ASCII -ErrorAction SilentlyContinue
}

# ---------------- 工具函数 ----------------
function Test-Port {
    param([string]$TargetHost, [int]$TargetPort, [int]$TimeoutMs = 5000)
    $tcp = New-Object System.Net.Sockets.TcpClient
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $ar = $tcp.BeginConnect($TargetHost, $TargetPort, $null, $null)
        $wait = $ar.AsyncWaitHandle.WaitOne($TimeoutMs, $false)
        if (-not $wait) {
            $tcp.Close(); $tcp.Dispose(); $sw.Stop()
            return [pscustomobject]@{ Ok = $false; Error = "TCP connect timeout (${TimeoutMs}ms)"; ElapsedMs = $sw.ElapsedMilliseconds }
        }
        $tcp.EndConnect($ar)
        $tcp.Close(); $tcp.Dispose(); $sw.Stop()
        return [pscustomobject]@{ Ok = $true; Error = ""; ElapsedMs = $sw.ElapsedMilliseconds }
    } catch {
        try { $tcp.Close(); $tcp.Dispose() } catch {}
        $sw.Stop()
        return [pscustomobject]@{ Ok = $false; Error = $_.Exception.Message; ElapsedMs = $sw.ElapsedMilliseconds }
    }
}

# 只取 $NginxDir 下的 nginx 进程，避免误杀其他目录的实例（Version 2 起的原意）
function Get-NginxProcess {
    Get-CimInstance Win32_Process -Filter "Name='nginx.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.ExecutablePath -like "$NginxDir*" }
}

# Y 盘（网络映射）是否可达 —— 不可达时一切重启尝试都没有意义
function Test-NginxTreeAvailable {
    if (Test-Path -LiteralPath $NginxExe) { return $true }
    return $false
}

function Restart-Nginx {
    # 前置：目录必须可达，否则重启必然失败（且 -s stop 会因读不到 pid 而报错刷屏）
    if (-not (Test-NginxTreeAvailable)) {
        Write-Log "无法重启：nginx 目录/可执行文件不可达 ($NginxExe)。Y 盘映射可能已失效。" "ERROR"
        Write-Log "  当前 Y: 映射状态请用 'net use' 检查；恢复映射后下一轮巡检会自动拉起。" "ERROR"
        return $false
    }

    # 优雅停止（-s stop）。注意必须在 $NginxDir 内执行，
    # 否则 nginx 会从错误位置读 logs\nginx.pid（2026-09-28 reload 事故的成因）。
    try {
        $p = Start-Process -FilePath $NginxExe -ArgumentList '-s','stop' `
             -WorkingDirectory $NginxDir -WindowStyle Hidden -Wait -PassThru -ErrorAction Stop
        Write-Log "已发出 nginx -s stop 信号 (exit $($p.ExitCode))" "WARN"
    } catch {
        Write-Log "nginx -s stop 失败: $($_.Exception.Message)" "WARN"
    }
    Start-Sleep -Seconds 3

    # 清理 $NginxDir 下仍残留的进程
    $procs = @(Get-NginxProcess)
    foreach ($proc in $procs) {
        try {
            Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop
            Write-Log "强制结束残留 nginx PID=$($proc.ProcessId) path=$($proc.ExecutablePath)" "WARN"
        } catch {
            Write-Log "结束 nginx PID=$($proc.ProcessId) 失败: $($_.Exception.Message)" "WARN"
        }
    }
    Start-Sleep -Seconds 2

    try {
        $p = Start-Process -FilePath $NginxExe -WorkingDirectory $NginxDir -WindowStyle Hidden -PassThru -ErrorAction Stop
        if ($p) { Write-Log "已启动 nginx (PID: $($p.Id))" "WARN" }
    } catch {
        Write-Log "启动失败: $($_.Exception.Message)" "ERROR"
        return $false
    }

    # 等待端口恢复
    $deadline = (Get-Date).AddSeconds($ReadyTimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 3
        if ((Test-Port -TargetHost $HostName -TargetPort $NginxPort -TimeoutMs 3000).Ok) {
            Write-Log "nginx 重启后已恢复服务" "INFO"
            return $true
        }
    }
    Write-Log "nginx 重启后 ${ReadyTimeoutSeconds}s 内仍未就绪" "ERROR"
    return $false
}

# =====================================================================
#  单次巡检（跑一轮就退出，由计划任务的周期提供重复性）
# =====================================================================

# ---- 0) 每次运行都记录一次「已运行」的心跳，便于确认任务真的在跑 ----
$alive = Test-Port -TargetHost $HostName -TargetPort $NginxPort -TimeoutMs $ConnectTimeoutMs

if ($alive.Ok) {
    # 正常：清零失败计数。只在计数由非 0 变 0 时写一行日志，避免每 5 分钟刷屏。
    $prev = Get-FailCount
    Set-FailCount 0
    if ($prev -gt 0) {
        Write-Log "端口 ${NginxPort} 已恢复（此前连续失败 $prev 轮）" "INFO"
    }
    Write-Log "OK port=$NginxPort host=$HostName ($($alive.ElapsedMs)ms)"
    exit 0
}

# ---- 异常：累计失败轮数 ----
$fails = (Get-FailCount) + 1
Set-FailCount $fails
Write-Log "端口 $NginxPort 在 $HostName 不可达 (第 $fails/$FailThreshold 轮) - $($alive.Error) ($($alive.ElapsedMs)ms)" "WARN"

if ($fails -lt $FailThreshold) {
    Write-Log "未达阈值 $FailThreshold 轮，本轮不重启（可能只是瞬时抖动）" "WARN"
    exit 0
}

# ---- 达到阈值：先看 Y 盘是否可达（网络映射盘专项防御） ----
if (-not (Test-NginxTreeAvailable)) {
    Write-Log "达到阈值，但 nginx 程序目录不可达 —— 只告警不重启。" "ERROR"
    Write-Log "  NginxExe=$NginxExe" "ERROR"
    Write-Log "  Y: 是网络映射 (\\\\192.168.100.19\\e)，映射失效/断网/切换用户时不可达。" "ERROR"
    Write-Log "  另：管理员会话可能看不到普通用户的映射盘，计划任务须以同一账户运行。" "ERROR"
    exit 1
}

# ---- 判断是「进程没了」还是「进程在但卡住」 ----
$svc = @(Get-NginxProcess)
if ($svc.Count -eq 0) {
    Write-Log "端口不可达且 $NginxDir 下无 nginx 进程 —— 执行重启" "WARN"
    Set-FailCount 0
    if (Restart-Nginx) { exit 0 } else { exit 1 }
}

$pids = ($svc | ForEach-Object { $_.ProcessId }) -join ','
$paths = ($svc | ForEach-Object { $_.ExecutablePath }) -join ','
Write-Log "端口不可达但 nginx 进程仍在 (PID=$pids)，path=$paths" "WARN"
Write-Log "按 Version 2 的既定策略：进程存活时不强制重启（可能只是繁忙）。若持续多轮无响应，请人工介入检查。" "WARN"
exit 0
