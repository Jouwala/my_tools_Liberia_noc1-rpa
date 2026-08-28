# Nginx Service Monitor - Fixed Version 2
# 修复：
# 1) 删除 PowerShell 不支持的 goto（原版本重启代码永远不会执行）
# 2) 探活地址从 127.0.0.1 改为实际服务地址 192.168.100.19
# 3) 用 nginx -s stop 优雅停止，只有残留进程才强杀
# 4) 杀进程范围收窄到 NginxDir，避免误杀其他 nginx
# 5) 重启后验证端口恢复
param(
    [string]$HostName = "192.168.100.19",
    [int]$NginxPort = 80,
    [string]$NginxExe = "E:\01_RPA\nginx-1.28.0\nginx.exe",
    [string]$NginxDir = "E:\01_RPA\nginx-1.28.0",
    [int]$CheckInterval = 5,
    [int]$FailThreshold = 5,
    [int]$ForceRestartMinutes = 10,
    [string]$LogPath = "D:\01_RPA\Task\nginx_monitor.log"
)

if (-not (Test-Path $LogPath)) { New-Item -Path $LogPath -ItemType File -Force | Out-Null }

function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $LogPath -Value "[$ts] [$Level] $Message" -Encoding UTF8
}

function Test-Port {
    param([string]$TargetHost, [int]$TargetPort, [int]$TimeoutMs = 10000)
    $tcp = New-Object System.Net.Sockets.TcpClient
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $ar = $tcp.BeginConnect($TargetHost, $TargetPort, $null, $null)
        $wait = $ar.AsyncWaitHandle.WaitOne($TimeoutMs, $false)
        if (-not $wait) {
            $tcp.Close()
            $tcp.Dispose()
            $sw.Stop()
            return [pscustomobject]@{ Ok = $false; Error = "TCP connect timeout (${TimeoutMs}ms)"; ElapsedMs = $sw.ElapsedMilliseconds }
        }
        $tcp.EndConnect($ar)
        $tcp.Close()
        $tcp.Dispose()
        $sw.Stop()
        return [pscustomobject]@{ Ok = $true; Error = ""; ElapsedMs = $sw.ElapsedMilliseconds }
    } catch {
        $tcp.Close()
        $tcp.Dispose()
        $sw.Stop()
        return [pscustomobject]@{ Ok = $false; Error = $_.Exception.Message; ElapsedMs = $sw.ElapsedMilliseconds }
    }
}

function Get-NginxProcess {
    Get-CimInstance Win32_Process -Filter "Name='nginx.exe'" |
        Where-Object { $_.ExecutablePath -like "$NginxDir*" } |
        Select-Object -First 1
}

function Restart-Nginx {
    if (-not (Test-Path -LiteralPath $NginxExe)) {
        Write-Log "Nginx not found at $NginxExe" "ERROR"
        return
    }

    # 优雅停止（nginx -s stop），不直接强杀
    try {
        $p = Start-Process -FilePath $NginxExe -ArgumentList '-s','stop' -WorkingDirectory $NginxDir -WindowStyle Hidden -Wait -PassThru -ErrorAction Stop
        Write-Log "Nginx stop signal sent (exit $($p.ExitCode))" "WARN"
    } catch {
        Write-Log "nginx -s stop failed: $($_.Exception.Message)" "WARN"
    }
    Start-Sleep -Seconds 3

    # 只清理 NginxDir 下仍残留的 nginx 进程，避免误杀其他目录的 nginx
    $procs = Get-CimInstance Win32_Process -Filter "Name='nginx.exe'" | Where-Object { $_.ExecutablePath -like "$NginxDir*" }
    foreach ($p in $procs) {
        try {
            Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
            Write-Log "Force killed nginx PID=$($p.ProcessId)" "WARN"
        } catch {
            Write-Log "Kill nginx PID=$($p.ProcessId) failed: $($_.Exception.Message)" "WARN"
        }
    }
    Start-Sleep -Seconds 2

    try {
        $p = Start-Process -FilePath $NginxExe -WorkingDirectory $NginxDir -WindowStyle Hidden -PassThru -ErrorAction Stop
        if ($p) { Write-Log "Nginx started (PID: $($p.Id))" "WARN" }
    } catch {
        Write-Log "Start failed: $($_.Exception.Message)" "ERROR"
        return
    }

    # 最多等 60 秒，确认端口恢复
    $ready = $false
    for ($i = 0; $i -lt 12; $i++) {
        Start-Sleep -Seconds 5
        $pCheck = Test-Port -TargetHost $HostName -TargetPort $NginxPort -TimeoutMs 5000
        if ($pCheck.Ok) {
            $ready = $true
            break
        }
    }
    if ($ready) { Write-Log "Nginx recovered after restart" "INFO" } else { Write-Log "Nginx not ready after restart" "ERROR" }
}

Write-Log "=== Nginx Monitor started (host=${HostName}:${NginxPort}, interval=${CheckInterval}s, threshold=${FailThreshold}) ==="

$failCount = 0
$unresponsiveSince = $null

while ($true) {
    $alive = Test-Port -TargetHost $HostName -TargetPort $NginxPort -TimeoutMs 10000

    if ($alive.Ok) {
        $failCount = 0
        $unresponsiveSince = $null
        Start-Sleep -Seconds $CheckInterval
        continue
    }

    if (-not $unresponsiveSince) { $unresponsiveSince = Get-Date }
    $failCount++
    Write-Log "Port $NginxPort unreachable on $HostName ($failCount/$FailThreshold) - $($alive.Error) ($($alive.ElapsedMs)ms)" "WARN"

    if ($failCount -ge $FailThreshold) {
        Write-Log "Port down ${FailThreshold}x, checking process..." "WARN"
        $failCount = 0
        $svc = Get-NginxProcess
        if ($svc) {
            $downFor = (Get-Date) - $unresponsiveSince
            if ($downFor.TotalMinutes -ge $ForceRestartMinutes) {
                Write-Log "Nginx process alive but unresponsive for $([int]$downFor.TotalMinutes) min, force restart..." "WARN"
                Restart-Nginx
                $unresponsiveSince = $null
            } else {
                Write-Log "Nginx process still alive (PID=$($svc.ProcessId)), port unresponsive - skip restart (likely busy, unresponsive $([int]$downFor.TotalSeconds)s)" "WARN"
            }
        } else {
            Restart-Nginx
            $unresponsiveSince = $null
        }
    }

    Start-Sleep -Seconds $CheckInterval
}
