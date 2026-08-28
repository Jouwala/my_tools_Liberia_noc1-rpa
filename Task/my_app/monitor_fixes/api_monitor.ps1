# API Service Monitor - Fixed Version 2
# 修复：
# 1) 删除 PowerShell 不支持的 goto（原版本重启代码永远不会执行）
# 2) 探活地址从 127.0.0.1 改为实际服务地址 192.168.100.19
# 3) 重启后轮询验证服务是否真正就绪
param(
    [string]$HostName = "192.168.100.19",
    [int]$Port = 8765,
    [string]$ScriptFile = "E:\01_RPA\db_writer_api.py",
    [string]$HealthUrl = "http://192.168.100.19:8765/health",
    [int]$CheckInterval = 5,
    [int]$FailThreshold = 5,
    [int]$ForceRestartMinutes = 10,
    [string]$LogPath = "D:\01_RPA\Task\api_monitor.log"
)

# 禁用系统代理，避免 SYSTEM 环境下 Invoke-WebRequest 走代理导致健康检查误判
[System.Net.WebRequest]::DefaultWebProxy = $null

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

function Test-Health {
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $r = Invoke-WebRequest -Uri $HealthUrl -TimeoutSec 15 -UseBasicParsing -ErrorAction Stop
        $sw.Stop()
        return [pscustomobject]@{ Ok = ($r.StatusCode -eq 200); Error = "HTTP $($r.StatusCode)"; ElapsedMs = $sw.ElapsedMilliseconds }
    } catch {
        $sw.Stop()
        return [pscustomobject]@{ Ok = $false; Error = $_.Exception.Message; ElapsedMs = $sw.ElapsedMilliseconds }
    }
}

function Find-Python {
    $proc = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like "*$ScriptFile*" } | Select-Object -First 1
    if ($proc) { return $proc.ExecutablePath }
    $paths = @("C:\Users\ZTEEMS\AppData\Local\Python\pythoncore-3.14-64\python.exe","C:\Users\ZTEEMS\.meituan-catpaw\runtimes\python\versions\3.12.13\python.exe")
    foreach ($p in $paths) { if (Test-Path $p) { return $p } }
    return "python.exe"
}

function Get-APIServiceProcess {
    Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
        Where-Object { $_.CommandLine -like "*$ScriptFile*" } |
        Select-Object -First 1
}

function Restart-APIService {
    if (-not (Test-Path -LiteralPath $ScriptFile)) {
        Write-Log "API script not found: $ScriptFile (监控器与服务不在同一台机器时无法本地重启)" "ERROR"
        return
    }

    # 精确杀掉匹配脚本路径的 python 进程
    $procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like "*$ScriptFile*" }
    foreach ($p in $procs) {
        try {
            Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
            Write-Log "Killed API process PID=$($p.ProcessId)" "WARN"
        } catch {
            Write-Log "Kill PID=$($p.ProcessId) failed: $($_.Exception.Message)" "WARN"
        }
    }
    Start-Sleep -Seconds 2

    $py = Find-Python
    $logDir = Split-Path $LogPath -Parent
    $outLog = Join-Path $logDir "api_runtime.log"
    $errLog = Join-Path $logDir "api_runtime.err.log"
    try {
        $p = Start-Process -FilePath $py -ArgumentList "`"$ScriptFile`"" -WorkingDirectory (Split-Path $ScriptFile -Parent) -WindowStyle Hidden -RedirectStandardOutput $outLog -RedirectStandardError $errLog -PassThru -ErrorAction Stop
        if ($p) { Write-Log "API started (PID: $($p.Id), logs: $outLog / $errLog)" "WARN" }
    } catch {
        Write-Log "Start failed: $($_.Exception.Message)" "ERROR"
        return
    }

    # 最多等 60 秒，确认端口和 /health 都恢复
    $ready = $false
    for ($i = 0; $i -lt 12; $i++) {
        Start-Sleep -Seconds 5
        $pCheck = Test-Port -TargetHost $HostName -TargetPort $Port -TimeoutMs 5000
        $hCheck = Test-Health
        if ($pCheck.Ok -and $hCheck.Ok) {
            $ready = $true
            break
        }
    }
    if ($ready) { Write-Log "API recovered after restart" "INFO" } else { Write-Log "API not ready after restart" "ERROR" }
}

Write-Log "=== API Monitor started (host=${HostName}:${Port}, interval=${CheckInterval}s, threshold=${FailThreshold}) ==="

$portFailCount = 0
$healthFailCount = 0
$unresponsiveSince = $null

while ($true) {
    $portResult = Test-Port -TargetHost $HostName -TargetPort $Port -TimeoutMs 10000

    if (-not $portResult.Ok) {
        if (-not $unresponsiveSince) { $unresponsiveSince = Get-Date }
        $portFailCount++
        Write-Log "Port $Port unreachable on $HostName ($portFailCount/$FailThreshold) - $($portResult.Error) ($($portResult.ElapsedMs)ms)" "WARN"
        if ($portFailCount -ge $FailThreshold) {
            Write-Log "Port down ${FailThreshold}x, checking process..." "WARN"
            $portFailCount = 0
            $healthFailCount = 0
            $svc = Get-APIServiceProcess
            if ($svc) {
                $downFor = (Get-Date) - $unresponsiveSince
                if ($downFor.TotalMinutes -ge $ForceRestartMinutes) {
                    Write-Log "API process alive but unresponsive for $([int]$downFor.TotalMinutes) min, force restart..." "WARN"
                    Restart-APIService
                    $unresponsiveSince = $null
                } else {
                    Write-Log "API process still alive (PID=$($svc.ProcessId)), port unresponsive - skip restart (likely busy, unresponsive $([int]$downFor.TotalSeconds)s)" "WARN"
                }
            } else {
                Restart-APIService
                $unresponsiveSince = $null
            }
        }
        Start-Sleep -Seconds $CheckInterval
        continue
    }

    $portFailCount = 0
    $health = Test-Health

    if (-not $health.Ok) {
        if (-not $unresponsiveSince) { $unresponsiveSince = Get-Date }
        $healthFailCount++
        Write-Log "Health check failed ($healthFailCount/$FailThreshold) - $($health.Error) ($($health.ElapsedMs)ms)" "WARN"
        if ($healthFailCount -ge $FailThreshold) {
            Write-Log "Health failed ${FailThreshold}x, checking process..." "WARN"
            $portFailCount = 0
            $healthFailCount = 0
            $svc = Get-APIServiceProcess
            if ($svc) {
                $downFor = (Get-Date) - $unresponsiveSince
                if ($downFor.TotalMinutes -ge $ForceRestartMinutes) {
                    Write-Log "API process alive but health failing for $([int]$downFor.TotalMinutes) min, force restart..." "WARN"
                    Restart-APIService
                    $unresponsiveSince = $null
                } else {
                    Write-Log "API process still alive (PID=$($svc.ProcessId)), health failing - skip restart (likely busy, unresponsive $([int]$downFor.TotalSeconds)s)" "WARN"
                }
            } else {
                Restart-APIService
                $unresponsiveSince = $null
            }
        }
    } else {
        $healthFailCount = 0
        $unresponsiveSince = $null
    }

    Start-Sleep -Seconds $CheckInterval
}
