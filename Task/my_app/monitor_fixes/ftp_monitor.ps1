# FTP Service Monitor - Fixed Version 2
# 修复：
# 1) 探活地址从 127.0.0.1 改为实际服务地址 192.168.100.19
# 2) 重启后验证 FTP 是否真正就绪（端口 + 220 握手）
# 3) 默认阈值从 3 提高到 5，减少网络抖动导致的误杀
param(
    [string]$HostName = "192.168.100.19",
    [int]$FtpPort = 21,
    [string]$FtpScript = "E:\01_RPA\ftp_server.py",
    [int]$CheckInterval = 5,
    [int]$FailThreshold = 5,
    [int]$ForceRestartMinutes = 10,
    [string]$LogPath = "D:\01_RPA\Task\ftp_monitor.log"
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

function Test-FTPBanner {
    param([string]$TargetHost, [int]$TargetPort, [int]$TimeoutMs = 5000)
    $tcp = New-Object System.Net.Sockets.TcpClient
    try {
        $ar = $tcp.BeginConnect($TargetHost, $TargetPort, $null, $null)
        $wait = $ar.AsyncWaitHandle.WaitOne($TimeoutMs, $false)
        if (-not $wait) {
            $tcp.Close()
            $tcp.Dispose()
            return $false
        }
        $tcp.EndConnect($ar)
        $stream = $tcp.GetStream()
        $stream.ReadTimeout = 3000
        $buffer = New-Object byte[] 256
        $read = $stream.Read($buffer, 0, $buffer.Length)
        $text = [System.Text.Encoding]::ASCII.GetString($buffer, 0, $read)
        $tcp.Close()
        $tcp.Dispose()
        return ($text -match '^220')
    } catch {
        $tcp.Close()
        $tcp.Dispose()
        return $false
    }
}

function Find-Python {
    $proc = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like "*$FtpScript*" } | Select-Object -First 1
    if ($proc) { return $proc.ExecutablePath }
    $paths = @("C:\Users\ZTEEMS\AppData\Local\Python\pythoncore-3.14-64\python.exe","C:\Users\ZTEEMS\.meituan-catpaw\runtimes\python\versions\3.12.13\python.exe")
    foreach ($p in $paths) { if (Test-Path $p) { return $p } }
    return "python.exe"
}

function Get-FTPServiceProcess {
    Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
        Where-Object { $_.CommandLine -like "*$FtpScript*" } |
        Select-Object -First 1
}

function Restart-FTPService {
    if (-not (Test-Path -LiteralPath $FtpScript)) {
        Write-Log "FTP script not found: $FtpScript (监控器与服务不在同一台机器时无法本地重启)" "ERROR"
        return
    }

    # 精确杀掉匹配脚本路径的 python 进程
    $procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like "*$FtpScript*" }
    foreach ($p in $procs) {
        try {
            Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
            Write-Log "Killed FTP process PID=$($p.ProcessId)" "WARN"
        } catch {
            Write-Log "Kill PID=$($p.ProcessId) failed: $($_.Exception.Message)" "WARN"
        }
    }
    Start-Sleep -Seconds 2

    $py = Find-Python
    try {
        $si = New-Object System.Diagnostics.ProcessStartInfo
        $si.FileName = $py
        $si.Arguments = "`"$FtpScript`""
        $si.WorkingDirectory = Split-Path $FtpScript -Parent
        $si.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
        $si.CreateNoWindow = $true
        $p = [System.Diagnostics.Process]::Start($si)
        if ($p) { Write-Log "FTP started (PID: $($p.Id))" "WARN" }
    } catch {
        Write-Log "Start failed: $($_.Exception.Message)" "ERROR"
        return
    }

    # 最多等 60 秒，确认端口和 FTP 220 握手都恢复
    $ready = $false
    for ($i = 0; $i -lt 12; $i++) {
        Start-Sleep -Seconds 5
        $pCheck = Test-Port -TargetHost $HostName -TargetPort $FtpPort -TimeoutMs 5000
        $bCheck = Test-FTPBanner -TargetHost $HostName -TargetPort $FtpPort
        if ($pCheck.Ok -and $bCheck) {
            $ready = $true
            break
        }
    }
    if ($ready) { Write-Log "FTP recovered after restart" "INFO" } else { Write-Log "FTP not ready after restart" "ERROR" }
}

Write-Log "=== FTP Monitor started (host=${HostName}:${FtpPort}, interval=${CheckInterval}s, threshold=${FailThreshold}) ==="

$failCount = 0
$unresponsiveSince = $null

while ($true) {
    $alive = Test-Port -TargetHost $HostName -TargetPort $FtpPort -TimeoutMs 10000

    if ($alive.Ok) {
        $failCount = 0
        $unresponsiveSince = $null
        Start-Sleep -Seconds $CheckInterval
        continue
    }

    if (-not $unresponsiveSince) { $unresponsiveSince = Get-Date }
    $failCount++
    Write-Log "Port $FtpPort unreachable on $HostName ($failCount/$FailThreshold) - $($alive.Error) ($($alive.ElapsedMs)ms)" "WARN"

    if ($failCount -ge $FailThreshold) {
        Write-Log "Port down ${FailThreshold}x, checking process..." "WARN"
        $failCount = 0
        $svc = Get-FTPServiceProcess
        if ($svc) {
            $downFor = (Get-Date) - $unresponsiveSince
            if ($downFor.TotalMinutes -ge $ForceRestartMinutes) {
                Write-Log "FTP process alive but unresponsive for $([int]$downFor.TotalMinutes) min, force restart..." "WARN"
                Restart-FTPService
                $unresponsiveSince = $null
            } else {
                Write-Log "FTP process still alive (PID=$($svc.ProcessId)), port unresponsive - skip restart (likely busy, unresponsive $([int]$downFor.TotalSeconds)s)" "WARN"
            }
        } else {
            Restart-FTPService
            $unresponsiveSince = $null
        }
    }

    Start-Sleep -Seconds $CheckInterval
}
