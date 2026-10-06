# Autostart + watchdog for the WhatsApp knowledge-base bot (src/index.js).
#
# IMPORTANT: keep this file pure ASCII.
# PowerShell 5.1 reads a UTF-8-without-BOM script as GBK, so any non-ASCII
# character (including Chinese in -match patterns) gets corrupted silently.
# That is why liveness is judged from the ASCII heartbeat JSON instead of the
# Chinese log labels.
#
# Modelled on autostart-notify.ps1 so the two daemons behave predictably.
# Those two daemons are INDEPENDENT and must both run:
#   * src/index.js  -> data/auth        (Q&A bot, this script)
#   * src/notify.js -> data/auth-notify (P1 alert push, autostart-notify.ps1)
# They use SEPARATE credential dirs, so one instance of each is correct and
# they do not kick each other off with 440. (An older comment in whatsapp.js
# claimed they shared data/auth; that was fixed and the comment corrected on
# 2026-10-06. Do not "fix" this by stopping one of them.)
#
# Usage:
#   .\autostart.ps1              # start if not running (idempotent)
#   .\autostart.ps1 -Watch       # same, but stays quiet unless it acts
#   .\autostart.ps1 -Status      # report state, change nothing
#   .\autostart.ps1 -Stop        # stop the bot gracefully

param(
  [switch]$Watch,
  [switch]$Status,
  [switch]$Stop
)

$ErrorActionPreference = 'Stop'

$dir     = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $dir 'bot.pid'
$logDir  = Join-Path $dir 'data\logs'
$hbFile  = Join-Path $dir 'data\bot_heartbeat.json'
$log     = Join-Path $logDir ("bot-" + (Get-Date -Format 'yyyy-MM-dd') + '.log')

# Heartbeat older than this counts as dead. The bot refreshes every 30s, so
# this leaves ~10x headroom for a slow tick while still noticing a real hang.
$staleSeconds = 300

# Find the bot by matching ONLY processes whose command line ends at the bot
# entry point. The previous version matched 'src[\\/]index\.js' anywhere in any
# node.exe command line, which produced false positives: on 2026-10-06 it
# matched an agent shell that merely MENTIONED the path, reported "already
# running", and wrote a bogus pid into bot.pid without starting anything.
# Requiring "node(.exe) ... src/index.js" with the path immediately after the
# node executable, and excluding shells/wrappers, closes that hole. The
# heartbeat remains the authoritative liveness signal; this is only a fallback
# for "process exists but heartbeat is not fresh yet" (i.e. still starting).
function Find-BotProcess {
  $procs = @(Get-CimInstance Win32_Process -Filter "Name='node.exe'" -ErrorAction SilentlyContinue)
  foreach ($p in $procs) {
    $cl = $p.CommandLine
    if (-not $cl) { continue }
    # Skip anything that is merely a wrapper for another command.
    if ($cl -match 'dsh-subprocess|powershell\.exe|-Command\s') { continue }
    # Must be: node [--flags] <path>\src\index.js  (path anchored to this bot)
    if ($cl -notmatch 'src[\\/]index\.js(\s|$|")') { continue }
    return $p
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

# Report "connected but no message has been handled for a long time".
#
# WHY THIS EXISTS (2026-10-06 incident): Test-Healthy above only proves the
# CONNECTION is up. That day the bot sat in a 408/428 reconnect loop - every
# successful reconnect rewrote connected=true, so the heartbeat stayed fresh,
# Test-Healthy returned true, and the watchdog never restarted it. Meanwhile
# the log contained zero '[reply]' lines: messages were not getting through.
# The fault ran for hours until a human noticed the bot ignoring people.
#
# lastMessageAt is the BUSINESS-level liveness signal; 'at'+'connected' is only
# TRANSPORT-level. When the two disagree, the business one is the truth.
#
# This only WARNS - it deliberately does not restart:
#   * a quiet group for hours is completely normal (this bot answers on @mention);
#   * restarting cannot fix "connected but deaf", and would interrupt service.
# So the point is to make the silent failure VISIBLE, not to auto-heal it.
function Test-Deaf {
  param([int]$DeafHours = 6)

  $hb = Get-Heartbeat
  if (-not $hb) { return $false }
  # Only meaningful while we believe we are connected and actually serving.
  if (-not $hb.connected) { return $false }
  if (-not $hb.lastMessageAt) { return $false }   # never handled one yet: not a signal

  try {
    $last = [datetime]::Parse($hb.lastMessageAt).ToUniversalTime()
  } catch {
    return $false
  }
  return (([datetime]::UtcNow - $last).TotalHours -ge $DeafHours)
}

function Write-DeafWarning {
  $hb = Get-Heartbeat
  $hours = try { [math]::Round(([datetime]::UtcNow - [datetime]::Parse($hb.lastMessageAt).ToUniversalTime()).TotalHours, 1) } catch { -1 }
  Write-Host "WARNING: whatsapp-kb-bot is connected but has not handled a message for ${hours}h."
  Write-Host "         lastMessageAt=$($hb.lastMessageAt) messagesHandled=$($hb.messagesHandled)"
  Write-Host "         Connection is up, so Test-Healthy says healthy - but messages may not be arriving."
  Write-Host "         Check: count reply lines in data\logs\bot-<date>.log"
  Write-Host "         Check: count reconnect cycles (a reconnect loop keeps connected=true forever)"
  Write-Host "         Check: data\auth\sender-key-*.json mtime - newer than start means decryption works"
}

function Show-Status {
  $p = Find-BotProcess
  $hb = Get-Heartbeat
  Write-Host "index.js process  : $(if ($p) { 'running (pid ' + $p.ProcessId + ')' } else { 'NOT running' })"
  if ($hb) {
    Write-Host "heartbeat         : at=$($hb.at) connected=$($hb.connected) pid=$($hb.pid)"
    $age = try { [int]([datetime]::UtcNow - [datetime]::Parse($hb.at).ToUniversalTime()).TotalSeconds } catch { -1 }
    Write-Host "heartbeat age     : ${age}s (stale threshold ${staleSeconds}s)"
    Write-Host "lastMessageAt     : $(if ($hb.lastMessageAt) { $hb.lastMessageAt } else { '(never)' })  handled=$($hb.messagesHandled)"
  } else {
    Write-Host "heartbeat         : (none)"
  }
  Write-Host "healthy           : $(Test-Healthy)"
  if (Test-Deaf) { Write-DeafWarning }
}

if ($Status) { Show-Status; exit 0 }

# Stop a node daemon.
#
# WHY NOT taskkill WITHOUT /F: `taskkill /PID x` posts WM_CLOSE to the target's
# window. These daemons run with -WindowStyle Hidden, so there is no message
# loop to receive it - measured on 2026-10-06, the process simply stayed alive
# and taskkill printed "could not be terminated" to stderr. (That stderr also
# tripped $ErrorActionPreference='Stop' and surfaced as a red NativeCommandError
# block.) Node's SIGINT handler does not help either: it only fires for a real
# console Ctrl+C, which a detached hidden process does not get.
#
# So the stop is: ask Stop-Process (which is TerminateProcess), then confirm.
# The graceful path is still preferred when it works - a plain Stop-Process
# lets Node run its 'exit' handlers; what it cannot do is wait for an in-flight
# Baileys credential write. autostart checks the pid and retries, and the
# heartbeat is marked disconnected below so a later -Watch does not mistake the
# leftover file for a live bot.
function Stop-BotProcess {
  param([int]$TargetPid)
  # 2>&1 keeps native stderr from becoming a terminating error under 'Stop'.
  $null = & taskkill.exe /PID $TargetPid /T /F 2>&1
  Start-Sleep -Seconds 2
  $still = Get-Process -Id $TargetPid -ErrorAction SilentlyContinue
  if ($still) {
    Stop-Process -Id $TargetPid -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
  }
}

if ($Stop) {
  $p = Find-BotProcess
  if (-not $p) {
    if (Test-Path $pidFile) { Remove-Item $pidFile -Force }
    Write-Host "whatsapp-kb-bot is not running"
    exit 0
  }
  Write-Host "stopping whatsapp-kb-bot (pid $($p.ProcessId)) ..."
  Stop-BotProcess -TargetPid $p.ProcessId

  $left = Find-BotProcess
  if ($left) {
    Write-Host "  warning: pid $($left.ProcessId) is still running"
  } else {
    Write-Host "whatsapp-kb-bot stopped"
  }

  if (Test-Path $pidFile) { Remove-Item $pidFile -Force }
  # Mark the heartbeat disconnected so a later -Watch does not mistake the
  # leftover file for a live bot.
  try {
    $hb = Get-Heartbeat
    if ($hb) {
      $hb.connected = $false
      $hb | ConvertTo-Json | Set-Content -Path $hbFile -Encoding UTF8
    }
  } catch { }
  exit 0
}

# --- start / watchdog path -------------------------------------------------

# Trust the heartbeat, not just the process list: a process can be alive but
# disconnected (e.g. sitting in a reconnect loop after a logout), in which case
# Q&A silently goes nowhere and a restart is the right move.
$existing = Find-BotProcess
if ($existing -and (Test-Healthy)) {
  $existing.ProcessId | Set-Content -Path $pidFile
  # Healthy by transport, but still check the business-level signal. This branch
  # is exactly where the 2026-10-06 fault hid: connection fine, watchdog happy,
  # bot deaf. Warn (do NOT restart) so a human can look.
  if (Test-Deaf) {
    Write-DeafWarning
  } elseif (-not $Watch) {
    Write-Host "whatsapp-kb-bot already running and healthy (pid $($existing.ProcessId))"
  }
  exit 0
}

if ($existing -and -not (Test-Healthy)) {
  # Alive but unhealthy: stale heartbeat or disconnected. Give a just-started
  # process a grace period first, otherwise the watchdog kills a bot that is
  # simply still completing its Baileys handshake.
  $graceOk = $false
  if ($existing.CreationDate) {
    $ageSec = ([datetime]::Now - $existing.CreationDate).TotalSeconds
    if ($ageSec -lt 90) {
      if (-not $Watch) { Write-Host "whatsapp-kb-bot pid $($existing.ProcessId) still starting (${ageSec}s old) - leaving it alone" }
      exit 0
    }
  }
  if (-not $graceOk) {
    Write-Host "whatsapp-kb-bot pid $($existing.ProcessId) is alive but NOT healthy - restarting"
    Stop-BotProcess -TargetPid $existing.ProcessId
  }
}

if (Test-Path $pidFile) { Remove-Item $pidFile -Force }
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }

# Launch detached and hidden. The project dir must be the working directory
# because .env and the relative paths in config.json are resolved from it.
$proc = Start-Process -FilePath 'node' `
  -ArgumentList '--env-file-if-exists=.env','src/index.js' `
  -WorkingDirectory $dir -WindowStyle Hidden -PassThru
$proc.Id | Set-Content -Path $pidFile

# Wait for the Baileys handshake. The bot writes data\bot_heartbeat.json with
# connected=true on a successful connect - a machine-readable marker, and the
# same mechanism autostart-notify.ps1 uses for notify.js.
$ok = $false
for ($i = 0; $i -lt 30; $i++) {
  Start-Sleep -Seconds 2
  if (Test-Healthy) { $ok = $true; break }
}

if ($ok) {
  Write-Host "whatsapp-kb-bot started and connected (pid $($proc.Id))"
  exit 0
}

if (-not (Get-Process -Id $proc.Id -ErrorAction SilentlyContinue)) {
  Write-Host "whatsapp-kb-bot exited immediately. Run it manually to see why:"
  Write-Host "  npm start"
  Write-Host "log: $log"
  exit 1
}

# Alive but not connected: the usual cause is invalidated credentials, which
# needs a QR scan. The window is hidden, so surface that instead of hanging.
Write-Host "whatsapp-kb-bot started (pid $($proc.Id)) but not connected within 60s."
Write-Host "Most likely the WhatsApp credentials were invalidated. Re-scan:"
Write-Host "  npm run relogin"
Write-Host "log: $log"
exit 0
