# Autostart for whatsapp-kb-bot (per-user, no admin needed).
# Idempotent: exits early if the bot is already running.
#
# IMPORTANT: keep this file pure ASCII.
# PowerShell 5.1 reads a UTF-8-without-BOM script as GBK, so any non-ASCII
# character (including Chinese in -match patterns) gets corrupted silently.
# That is why the connected-check below looks for '@s.whatsapp.net' instead
# of the Chinese "connected" label in the log.

$ErrorActionPreference = 'Stop'

$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $dir 'bot.pid'
$logDir  = Join-Path $dir 'data\logs'

function Find-BotProcess {
  $procs = @(Get-CimInstance Win32_Process -Filter "Name='node.exe'" -ErrorAction SilentlyContinue)
  foreach ($p in $procs) {
    if ($p.CommandLine -and ($p.CommandLine -match 'src[\\/]index\.js')) { return $p }
  }
  return $null
}

# 1. Already running? Do nothing. Scanning the command line (not just the pid
#    file) is deliberate: after a hard reboot the pid file is stale and the pid
#    may have been reused by an unrelated process.
$existing = Find-BotProcess
if ($existing) {
  $existing.ProcessId | Set-Content -Path $pidFile
  Write-Host "whatsapp-kb-bot already running (pid $($existing.ProcessId))"
  exit 0
}

if (Test-Path $pidFile) { Remove-Item $pidFile -Force }
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }

$log = Join-Path $logDir ("bot-" + (Get-Date -Format 'yyyy-MM-dd') + '.log')

# 2. Launch detached, hidden, with the project dir as working directory
#    (needed because .env and src/index.js are relative paths).
$proc = Start-Process -FilePath 'node' `
  -ArgumentList '--env-file-if-exists=.env','src/index.js' `
  -WorkingDirectory $dir -WindowStyle Hidden -PassThru
$proc.Id | Set-Content -Path $pidFile

# 3. Wait for the Baileys handshake. The bot logs its own JID
#    (...@s.whatsapp.net) on a successful connect, and that marker is ASCII.
$connected = $false
for ($i = 0; $i -lt 30; $i++) {
  Start-Sleep -Seconds 2
  if (Test-Path $log) {
    try {
      $t = Get-Content $log -Raw -ErrorAction SilentlyContinue
      if ($t -and $t.Contains('@s.whatsapp.net')) { $connected = $true; break }
    } catch { }
  }
}

if ($connected) {
  Write-Host "whatsapp-kb-bot connected (pid $($proc.Id))"
  exit 0
}

if (-not (Get-Process -Id $proc.Id -ErrorAction SilentlyContinue)) {
  Write-Host "whatsapp-kb-bot exited immediately. Run it manually to see why: npm start"
  exit 1
}

# Still alive but no handshake: most likely it is waiting for a QR scan.
# The window is hidden, so a QR code would be invisible -- go manual.
Write-Host "whatsapp-kb-bot started (pid $($proc.Id)) but not connected within 60s."
Write-Host "If it needs a QR scan, stop it and run manually: npm start"
Write-Host "log: $log"
exit 0
