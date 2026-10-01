# Autostart + watchdog for the P1 alert push daemon (src/notify.js).
#
# IMPORTANT: keep this file pure ASCII.
# PowerShell 5.1 reads a UTF-8-without-BOM script as GBK, so any non-ASCII
# character (including Chinese in -match patterns) gets corrupted silently.
# That is why the connected-check below looks for the heartbeat's
# '"connected": true' JSON instead of the Chinese log label.
#
# Modelled on autostart.ps1 (same process-scan and hidden-launch approach) so
# the two daemons behave predictably. Differences, and why:
#   * notify.js is the P1 ALERT channel. If it is down, on-call gets nothing.
#     So this script also serves as a WATCHDOG (see -Watch) and is registered
#     to run every 5 minutes, whereas autostart.ps1 is start-once.
#   * Liveness is judged from data\notify_heartbeat.json, which notify.js
#     rewrites every few seconds. A pid file alone is not enough: after a hard
#     kill the pid file is stale and the pid may be reused.
#
# Usage:
#   .\autostart-notify.ps1              # start if not running (idempotent)
#   .\autostart-notify.ps1 -Watch       # same, but stays quiet unless it acts
#   .\autostart-notify.ps1 -Status      # report state, change nothing
#   .\autostart-notify.ps1 -Stop        # stop the daemon

param(
  [switch]$Watch,
  [switch]$Status,
  [switch]$Stop
)

$ErrorActionPreference = 'Stop'

$dir        = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile    = Join-Path $dir 'notify.pid'
$logDir     = Join-Path $dir 'data\logs'
$hbFile     = Join-Path $dir 'data\notify_heartbeat.json'
$log        = Join-Path $logDir ("notify-" + (Get-Date -Format 'yyyy-MM-dd') + '.log')

# Heartbeat older than this counts as dead. Must stay >= the daemon's own
# poll interval (NOTIFY_POLL_MS, default 5s) with generous headroom, and should
# match the backend's WA_NOTIFY_HEARTBEAT_SECONDS so both sides agree.
$staleSeconds = 300

function Find-NotifyProcess {
  $procs = @(Get-CimInstance Win32_Process -Filter "Name='node.exe'" -ErrorAction SilentlyContinue)
  foreach ($p in $procs) {
    if ($p.CommandLine -and ($p.CommandLine -match 'src[\\/]notify\.js')) { return $p }
  }
  return $null
}

function Get-Heartbeat {
  if (-not (Test-Path $hbFile)) { return $null }
  try {
    $raw = Get-Content $hbFile -Raw -Encoding UTF8 -ErrorAction Stop
    return ($raw | ConvertFrom-Json)
  } catch {
    return $null
  }
}

function Test-Healthy {
  $hb = Get-Heartbeat
  if (-not $hb) { return $false }
  if (-not $hb.connected) { return $false }
  try {
    $at = [datetime]::Parse($hb.at).ToUniversalTime()
  } catch {
    return $false
  }
  $age = ([datetime]::UtcNow - $at).TotalSeconds
  return ($age -le $staleSeconds)
}

function Show-Status {
  $p = Find-NotifyProcess
  $hb = Get-Heartbeat
  Write-Host "notify.js process : $(if ($p) { 'running (pid ' + $p.ProcessId + ')' } else { 'NOT running' })"
  if ($hb) {
    Write-Host "heartbeat         : at=$($hb.at) connected=$($hb.connected) groups=$($hb.groups) pid=$($hb.pid)"
    $age = try { [int]([datetime]::UtcNow - [datetime]::Parse($hb.at).ToUniversalTime()).TotalSeconds } catch { -1 }
    Write-Host "heartbeat age     : ${age}s (stale threshold ${staleSeconds}s)"
  } else {
    Write-Host "heartbeat         : (none)"
  }
  Write-Host "healthy           : $(Test-Healthy)"
}

if ($Status) { Show-Status; exit 0 }

if ($Stop) {
  $p = Find-NotifyProcess
  if (-not $p) { Write-Host "notify.js is not running"; exit 0 }
  # Ask nicely first so Baileys can flush creds; a hard kill can corrupt
  # data\auth and force a QR re-scan (same reason index.js traps SIGINT).
  Stop-Process -Id $p.ProcessId -ErrorAction SilentlyContinue
  Start-Sleep -Seconds 3
  $still = Find-NotifyProcess
  if ($still) { Stop-Process -Id $still.ProcessId -Force -ErrorAction SilentlyContinue }
  if (Test-Path $pidFile) { Remove-Item $pidFile -Force }
  Write-Host "notify.js stopped"
  exit 0
}

# --- start / watchdog path -------------------------------------------------

# Trust the heartbeat, not just the process list: a process can be alive but
# not connected (e.g. waiting after a logout), in which case alerts silently
# go nowhere and a restart is the right move.
$existing = Find-NotifyProcess
if ($existing -and (Test-Healthy)) {
  $existing.ProcessId | Set-Content -Path $pidFile
  if (-not $Watch) { Write-Host "notify.js already running and healthy (pid $($existing.ProcessId))" }
  exit 0
}

if ($existing -and -not (Test-Healthy)) {
  # Alive but unhealthy: stale heartbeat or disconnected. Restart it.
  Write-Host "notify.js pid $($existing.ProcessId) is alive but NOT healthy - restarting"
  Stop-Process -Id $existing.ProcessId -ErrorAction SilentlyContinue
  Start-Sleep -Seconds 3
  $still = Find-NotifyProcess
  if ($still) { Stop-Process -Id $still.ProcessId -Force -ErrorAction SilentlyContinue }
}

if (Test-Path $pidFile) { Remove-Item $pidFile -Force }
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }

$proc = Start-Process -FilePath 'node' `
  -ArgumentList '--env-file-if-exists=.env','src/notify.js' `
  -WorkingDirectory $dir -WindowStyle Hidden -PassThru
$proc.Id | Set-Content -Path $pidFile

# Wait for the Baileys handshake. notify.js writes the heartbeat on connect,
# which is a machine-readable marker (autostart.ps1 sniffed a log string;
# the heartbeat is strictly better because the backend reads the same file).
$ok = $false
for ($i = 0; $i -lt 30; $i++) {
  Start-Sleep -Seconds 2
  if (Test-Healthy) { $ok = $true; break }
}

if ($ok) {
  Write-Host "notify.js started and connected (pid $($proc.Id))"
  exit 0
}

if (-not (Get-Process -Id $proc.Id -ErrorAction SilentlyContinue)) {
  Write-Host "notify.js exited immediately. Run it manually to see why:"
  Write-Host "  node --env-file-if-exists=.env src/notify.js --check"
  exit 1
}

# Alive but not connected: the usual cause is invalidated credentials, which
# needs a QR scan. The window is hidden, so surface that instead of hanging.
Write-Host "notify.js started (pid $($proc.Id)) but not connected within 60s."
Write-Host "Most likely the WhatsApp credentials were invalidated. Re-scan:"
Write-Host "  npm run relogin"
Write-Host "log: $log"
exit 0
