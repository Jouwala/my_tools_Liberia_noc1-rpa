# Autostart + watchdog for the WhatsApp knowledge-base bot (src/index.js) and
# the web Q&A assistant (src/http-server.js on :9269).
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
# This script ALSO supervises the web Q&A assistant (src/http-server.js on :9269),
# the HTTP wrapper behind the portal's bottom-right help widget. It reuses the
# same routeAnswer() as the group bot, so it is the same answer engine exposed
# over HTTP. Both daemons are kept alive here so a reboot brings both up, and
# the 5-minute watchdog restarts either one if it dies. The web assistant has
# no heartbeat JSON (liveness is a TCP probe on 127.0.0.1:9269), so it is judged
# differently from the bot, which trusts data\bot_heartbeat.json.
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

# PowerShell 5.1 Start-Process copies the parent env block into a case-insensitive
# dictionary; if the host has the same variable under two casings (HTTPS_PROXY +
# https_proxy - common when a proxy is injected into the shell) it throws
# "Item has already been added" and the launch fails. Drop the lowercase proxy
# duplicates here: the real config comes from .env via --env-file-if-exists.
foreach ($k in @('http_proxy', 'https_proxy', 'all_proxy', 'no_proxy')) {
  if (Test-Path "env:$k") { Remove-Item -Path "env:$k" -ErrorAction SilentlyContinue }
}

$dir     = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $dir 'bot.pid'
$logDir  = Join-Path $dir 'data\logs'
$hbFile  = Join-Path $dir 'data\bot_heartbeat.json'
$log     = Join-Path $logDir ("bot-" + (Get-Date -Format 'yyyy-MM-dd') + '.log')

# Web Q&A assistant (:9269). Same watchdog pattern as the bot: a pid file plus a
# log. Health is a TCP probe, not a heartbeat file (see Test-HttpServerHealthy).
$httpPidFile = Join-Path $dir 'http-server.pid'
$httpLog     = Join-Path $logDir ("http-server-" + (Get-Date -Format 'yyyy-MM-dd') + '.log')
$httpErrLog  = Join-Path $logDir ("http-server-" + (Get-Date -Format 'yyyy-MM-dd') + '.err.log')
$httpPort    = 9269

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

# Same anchoring idea as Find-BotProcess, but for the web Q&A assistant.
function Find-HttpServerProcess {
  $procs = @(Get-CimInstance Win32_Process -Filter "Name='node.exe'" -ErrorAction SilentlyContinue)
  foreach ($p in $procs) {
    $cl = $p.CommandLine
    if (-not $cl) { continue }
    if ($cl -match 'dsh-subprocess|powershell\.exe|-Command\s') { continue }
    # Must be: node [--flags] <path>\src\http-server.js
    if ($cl -notmatch 'src[\\/]http-server\.js(\s|$|")') { continue }
    return $p
  }
  return $null
}

# Delete a pid file via .NET instead of Remove-Item.
# In some environments Remove-Item is wrapped by a "safe delete" hook that
# forwards the file to the Recycle Bin; when the Recycle Bin is unavailable the
# hook THROWS, which used to abort the whole -Stop / start sequence halfway
# (observed 2026-11-04: bot.pid delete failed and the bot never restarted).
function Remove-PidFile {
  param([string]$Path)
  try {
    if ($Path -and [System.IO.File]::Exists($Path)) {
      [System.IO.File]::Delete($Path)
    }
  } catch { }
}

# Liveness for the web assistant: a process whose command line is exactly our
# http-server.js AND the port is actually accepting connections. We use a raw
# TCP probe instead of GET /health because /health triggers an Ollama model-list
# call whose timeout balloons to 10s+ when Ollama is down - that would make the
# watchdog think the assistant is dead and thrash it. TCP-open is the right
# level: it answers the only question that matters to the portal ("can I reach
# :9269?").
function Test-HttpServerHealthy {
  param([int]$Port = $httpPort)
  $proc = Find-HttpServerProcess
  if (-not $proc) { return $false }
  $tcp = $null
  try {
    $tcp = New-Object System.Net.Sockets.TcpClient
    $iar = $tcp.BeginConnect('127.0.0.1', $Port, $null, $null)
    if ($iar.AsyncWaitHandle.WaitOne(3000, $false) -and $tcp.Connected) {
      return $true
    }
    return $false
  } catch {
    return $false
  } finally {
    if ($tcp) { try { $tcp.Close() } catch { } }
  }
}

# Launch the web assistant detached and hidden, mirroring the bot launch below.
# stdout/stderr go to dated files because the process has no internal logger.
function Start-HttpServer {
  if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
  $proc = Start-Process -FilePath 'node' `
    -ArgumentList '--env-file-if-exists=.env','src/http-server.js' `
    -WorkingDirectory $dir -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $httpLog -RedirectStandardError $httpErrLog
  $proc.Id | Set-Content -Path $httpPidFile
  return $proc
}

# Idempotent: start only if not already healthy; restart if alive-but-not-serving.
function Ensure-HttpServer {
  $existing = Find-HttpServerProcess
  $healthy  = Test-HttpServerHealthy
  if ($existing -and $healthy) {
    $existing.ProcessId | Set-Content -Path $httpPidFile
    if (-not $Watch) {
      Write-Host "whatsapp-kb http-server already running and healthy (pid $($existing.ProcessId))"
    }
    return
  }
  if ($existing -and -not $healthy) {
    $ageSec = if ($existing.CreationDate) { ([datetime]::Now - $existing.CreationDate).TotalSeconds } else { 999 }
    if ($ageSec -lt 30) {
      if (-not $Watch) { Write-Host "whatsapp-kb http-server pid $($existing.ProcessId) still starting (${ageSec}s old) - leaving it alone" }
      return
    }
    Write-Host "whatsapp-kb http-server pid $($existing.ProcessId) alive but NOT healthy - restarting"
    Stop-BotProcess -TargetPid $existing.ProcessId
  }
  Remove-PidFile -Path $httpPidFile
  $p = Start-HttpServer
  # Brief wait for the listener to bind.
  $ok = $false
  for ($i = 0; $i -lt 15; $i++) {
    Start-Sleep -Seconds 1
    if (Test-HttpServerHealthy) { $ok = $true; break }
  }
  if ($ok) {
    Write-Host "whatsapp-kb http-server started and listening (pid $($p.Id))"
  } else {
    Write-Host "whatsapp-kb http-server started (pid $($p.Id)) but not listening on :$httpPort within 15s. Check $httpLog"
  }
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

  # Web Q&A assistant (:9269)
  $hp = Find-HttpServerProcess
  $hh = Test-HttpServerHealthy
  Write-Host "http-server proc  : $(if ($hp) { 'running (pid ' + $hp.ProcessId + ')' } else { 'NOT running' })"
  Write-Host "http-server healthy: $hh (port $httpPort)"
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
  # Order matters: stop the http-server FIRST, then the group bot.
  # 2026-11-04 fix: the old code did "exit 0" when the bot was not running,
  # which skipped the whole http-server stop block below. Result: -Stop said
  # "not running" while :9269 kept serving the OLD datadomains.js, so the web
  # assistant and the group bot behaved differently after a code change.
  $hp = Find-HttpServerProcess
  if ($hp) {
    Write-Host "stopping whatsapp-kb http-server (pid $($hp.ProcessId)) ..."
    Stop-BotProcess -TargetPid $hp.ProcessId
    $hleft = Find-HttpServerProcess
    if ($hleft) { Write-Host "  warning: http-server pid $($hleft.ProcessId) is still running" }
    else { Write-Host "whatsapp-kb http-server stopped" }
  } else {
    Write-Host "whatsapp-kb http-server is not running"
  }
  Remove-PidFile -Path $httpPidFile

  $p = Find-BotProcess
  if (-not $p) {
    Remove-PidFile -Path $pidFile
    # Mark the heartbeat disconnected so a later -Watch does not mistake the
    # leftover file for a live bot.
    try {
      $hb = Get-Heartbeat
      if ($hb) {
        $hb.connected = $false
        $hb | ConvertTo-Json | Set-Content -Path $hbFile -Encoding UTF8
      }
    } catch { }
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

  Remove-PidFile -Path $pidFile
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

# --- offline alert via the notify mailbox -----------------------------------
# The bot cannot report its own death, but notify.js runs on separate
# credentials (data/auth-notify) and polls data/notify_job.json every 5s.
# After N consecutive unhealthy checks we drop ONE text job into that mailbox
# and notify delivers it to the ops group. 2026-10-12~14 lesson: a 440 war kept
# the bot effectively dead for 34h and nothing alerted anyone. State persists
# in data\watchdog_alert.json because every watchdog run is a fresh process.
# NOTE: all JSON writes below are UTF-8 WITHOUT BOM on purpose - notify.js
# reads these files with JSON.parse(readFileSync(..., 'utf8')) and a BOM
# makes the parse fail, silently dropping the alert.
$alertStateFile = Join-Path $dir 'data\watchdog_alert.json'
$notifyJobFile  = Join-Path $dir 'data\notify_job.json'
$alertGroups    = @('*P1 OLR ZTE MS Manager*')  # resolveGroup() matches display names
$alertStreakMax = 3                             # 3 failed checks = ~15 min down

function Get-AlertState {
  if (-not (Test-Path $alertStateFile)) { return $null }
  try { return (Get-Content $alertStateFile -Raw -Encoding UTF8 | ConvertFrom-Json) } catch { return $null }
}

function Set-AlertState {
  param([int]$Streak, [bool]$Alerted)
  $o = [ordered]@{ streak = $Streak; alerted = $Alerted; at = (Get-Date).ToUniversalTime().ToString('o') }
  [System.IO.File]::WriteAllText($alertStateFile, ($o | ConvertTo-Json), (New-Object System.Text.UTF8Encoding($false)))
}

function Send-OfflineAlert {
  param([int]$Streak)
  # Never clobber a job notify has not finished with (pending/running).
  if (Test-Path $notifyJobFile) {
    try {
      $cur = Get-Content $notifyJobFile -Raw -Encoding UTF8 | ConvertFrom-Json
      if ($cur -and ($cur.status -eq 'pending' -or $cur.status -eq 'running')) { return $false }
    } catch { }
  }
  $hb = Get-Heartbeat
  $hbInfo = if ($hb) { "last heartbeat at=$($hb.at) connected=$($hb.connected)" } else { 'no heartbeat file' }
  $text = "WATCHDOG ALERT: whatsapp Q&A bot has failed $Streak health checks (~$($Streak * 5) minutes down or not connected). $hbInfo. " +
          'The watchdog keeps restarting it. If the log shows code=440, a duplicate process is using the same credentials (see AGENTS notes in autostart.ps1).'
  $job = [ordered]@{
    job_id     = 'watchdog-' + (Get-Date -Format 'yyyyMMddHHmmss') + '-' + ([guid]::NewGuid().ToString('N').Substring(0, 8))
    kind       = 'text'
    status     = 'pending'
    groups     = $alertGroups
    messages   = @([ordered]@{ text = $text })
    created_at = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ss')
  }
  [System.IO.File]::WriteAllText($notifyJobFile, ($job | ConvertTo-Json -Depth 5), (New-Object System.Text.UTF8Encoding($false)))
  return $true
}

function Update-OfflineAlertState {
  # Called whenever the bot is NOT healthy at this check. One alert per episode.
  $st = Get-AlertState
  $streak = 0
  $alerted = $false
  if ($st) {
    if ($st.streak)  { $streak = [int]$st.streak }
    if ($st.alerted) { $alerted = [bool]$st.alerted }
  }
  $streak++
  if ($streak -ge $alertStreakMax -and -not $alerted) {
    if (Send-OfflineAlert -Streak $streak) {
      $alerted = $true
      Write-Host "offline alert queued into notify mailbox (streak $streak)"
    }
  }
  Set-AlertState -Streak $streak -Alerted $alerted
}

function Reset-OfflineAlertState {
  $st = Get-AlertState
  if ($st -and (($st.streak -and [int]$st.streak -gt 0) -or $st.alerted)) {
    Set-AlertState -Streak 0 -Alerted $false
    Write-Host 'bot healthy again - offline alert state reset'
  }
}

# --- start / watchdog path -------------------------------------------------

# Keep the web Q&A assistant alive FIRST, independent of the bot below. This runs
# on every tick (boot + 5-min watchdog), so a reboot or a crash both self-heal.
Ensure-HttpServer

# Trust the heartbeat, not just the process list: a process can be alive but
# disconnected (e.g. sitting in a reconnect loop after a logout), in which case
# Q&A silently goes nowhere and a restart is the right move.
$existing = Find-BotProcess
$healthy  = Test-Healthy
# Offline alert bookkeeping happens exactly once per check, on both branches.
if ($healthy) { Reset-OfflineAlertState } else { Update-OfflineAlertState }
if ($existing -and $healthy) {
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

if ($existing -and -not $healthy) {
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

Remove-PidFile -Path $pidFile
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
