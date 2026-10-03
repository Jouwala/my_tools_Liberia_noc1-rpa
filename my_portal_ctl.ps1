# =============================================================================
#  my_portal_ctl.ps1 - single entry point behind every desktop shortcut
#
#  WHY THIS FILE EXISTS (do not delete, do not rename):
#  The portal directory name contains Chinese characters
#  ("liberia-noc_soc-数据看板统一门户"). This machine's ANSI codepage is
#  Windows-1252, which cannot round-trip those characters into a .lnk, so a
#  shortcut pointing straight at the portal's start.bat would be corrupted.
#  Every shortcut therefore points HERE - this filename is pure ASCII - and
#  the portal directory is resolved at run time by wildcard matching.
#
#  USER-VISIBLE CONTRACT (what the shortcuts promise):
#    * Double-click runs it; a console window shows what is happening.
#    * The window ends with "press any key to close"; the services keep
#      running in the background after the window closes.
#
#  USAGE
#    powershell -NoProfile -ExecutionPolicy Bypass -File my_portal_ctl.ps1 <command>
#
#  Commands map 1:1 to the shortcuts:
#    0-status        0-status.lnk        port check + entry URLs
#    1-start-nginx   1-start_nginx.lnk   pop up start_nginx.bat (skips if already up)
#    2-stop-nginx    2-stop_nginx.lnk    pop up stop_nginx.bat  (signals from nginx's own dir)
#    3-reload-nginx  3-reload_nginx.lnk  pop up reload_nginx.bat (nginx -t first, reload only if valid)
#    4-start-myapp   4-start_myapp.lnk   run Task\my_app\start.bat
#    5-stop-myapp    5-stop_myapp.lnk    run Task\my_app\stop.bat (writes stopped.flag)
#    6-start-portal  6-start_portal.lnk  run <portal>\start.bat
#    7-stop-portal   7-stop_portal.lnk   run <portal>\stop.bat
#    8-start-all     8-start_all.lnk     my_app -> portal -> nginx (nginx silent)
#    9-stop-all      9-stop_all.lnk      nginx -> portal -> my_app
#
#  DESIGN NOTES
#    * Windows PowerShell 5.1 only - this box has no pwsh.exe. Keep the script
#      5.1-compatible (no ternary operator, no -Parallel, no ::new() niceties).
#    * Child .bat files are started with Start-Process (a real console each) and
#      waited on, so the operator reads each report window before it closes.
#    * my_app and portal single-service shortcuts intentionally DELEGATE to the
#      .bat files already in the repo rather than reimplementing their stop
#      logic (layered kill + stopped.flag + optional UAC retry). Duplicating
#      that here would create a second source of truth.
# =============================================================================

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Command = "0-status",

    # 8-start-all / 9-stop-all: run nginx without popping a window of its own.
    [switch]$Quiet
)

$ErrorActionPreference = 'Continue'

# ---------------------------------------------------------------------------
#  Paths - resolved at run time, never baked into a .lnk
# ---------------------------------------------------------------------------

# This script's own directory is the stable anchor for everything else.
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# Workspace root. The script lives at the root today; fall back to a search so
# the shortcut keeps working if the file is ever moved one level down.
$Root = $ScriptDir
if (-not (Test-Path (Join-Path $Root 'Task\my_app'))) {
    foreach ($candidate in @((Split-Path -Parent $ScriptDir), 'D:\01_RPA')) {
        if ($candidate -and (Test-Path (Join-Path $candidate 'Task\my_app'))) {
            $Root = $candidate
            break
        }
    }
}

$MyAppDir  = Join-Path $Root 'Task\my_app'
$NginxDir  = Join-Path $Root 'nginx-1.28.0'
$NginxExe  = Join-Path $NginxDir 'nginx.exe'

# Portal directory: name is non-ASCII, so match it by wildcard. The distinctive
# ASCII prefix/suffix avoids hardcoding Chinese text in this file at all.
function Resolve-PortalDir {
    # Preferred: the known prefix, wildcarded.
    $hit = Get-ChildItem -LiteralPath $Root -Directory -ErrorAction SilentlyContinue |
           Where-Object { $_.Name -like 'liberia-noc_soc-*' } |
           Select-Object -First 1
    if ($hit) { return $hit.FullName }

    # Fallback: any directory holding the portal's own start.bat.
    $hit = Get-ChildItem -LiteralPath $Root -Directory -ErrorAction SilentlyContinue |
           Where-Object { Test-Path (Join-Path $_.FullName 'start_hidden.ps1') } |
           Select-Object -First 1
    if ($hit) { return $hit.FullName }

    return $null
}

$PortalDir = Resolve-PortalDir

# ---------------------------------------------------------------------------
#  Ports / entry points (the status view and the "already running" checks)
# ---------------------------------------------------------------------------

# Port -> what it is. Ordered so the status view lists them in port order.
# NOTE: [ordered] hashtable keys are strings, so every lookup must cast the
# port to [string] - $PortMap[80] would silently miss and print a blank label.
$PortMap = [ordered]@{
    '80'   = 'nginx HTTP  (redirects to HTTPS)'
    '443'  = 'nginx HTTPS (all entry points)'
    '7038' = 'my_app backend (FastAPI)'
    '7090' = 'my_app frontend (vite)'
    '9267' = 'portal (uniplam)'
    '9268' = 'portal WhatsApp analysis'
}

$EntryPoints = @(
    @{ Url = 'https://localhost/myapp/';             Name = 'Data Insight MVP' }
    @{ Url = 'https://localhost/uniplam/';           Name = 'Unified portal' }
    @{ Url = 'https://localhost/v1/olbrportal/';     Name = 'OLR static shell v1' }
    @{ Url = 'https://localhost/olbrportal/';        Name = 'OLR static shell (original)' }
    @{ Url = 'https://localhost/MsPortal/';          Name = 'MsPortal' }
    @{ Url = 'https://localhost/webroot/decision';   Name = 'FineBI (on .19, proxied here)' }
)

# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

function Write-Head {
    param([string]$Title)
    Write-Host ''
    Write-Host '============================================' -ForegroundColor Cyan
    Write-Host "  $Title" -ForegroundColor Cyan
    Write-Host '============================================' -ForegroundColor Cyan
    Write-Host ''
}

function Write-Step { param([string]$Message) Write-Host "[*] $Message" }
function Write-Ok   { param([string]$Message) Write-Host "[OK] $Message"   -ForegroundColor Green }
function Write-Warn { param([string]$Message) Write-Host "[WARN] $Message" -ForegroundColor Yellow }
function Write-Err  { param([string]$Message) Write-Host "[FAIL] $Message" -ForegroundColor Red }

# Is something listening on this port? TCP connect is the honest test - it
# fails when the port is bound but wedged, unlike a netstat string match.
function Test-PortListening {
    param([int]$Port, [int]$TimeoutMs = 1500, [string]$TargetHost = '127.0.0.1')
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect($TargetHost, $Port, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne($TimeoutMs, $false)) { return $false }
        $client.EndConnect($async)
        return $true
    } catch {
        return $false
    } finally {
        try { $client.Close(); $client.Dispose() } catch { }
    }
}

# Run a repo .bat in its OWN console window so the operator can read its report.
#
# WHY A SEPARATE WINDOW: these bats already handle their own hard parts (layered
# process kills, stopped.flag, UAC retry, nginx's own-directory signal). Running
# them with Start-Process gives each one a genuine console, so their output and
# any UAC prompt behave exactly as they do when double-clicked directly.
#
# WHY STDIN IS REDIRECTED: every one of these bats ends with `pause >nul`,
# which waits for a keypress. If we did not redirect, the operator would have
# to press a key once per bat AND again for this controller - and 8-start_all
# runs three bats, so that is four separate keypresses. Redirecting an empty
# input stream makes each child's `pause` return immediately; the child window
# still prints its full report and closes itself, and the single "press any key"
# prompt the user was promised happens once, in this controller's window.
function Invoke-ChildBat {
    param(
        [Parameter(Mandatory = $true)][string]$BatPath,
        [string]$WorkDir,
        [switch]$Hidden
    )

    if (-not (Test-Path -LiteralPath $BatPath)) {
        Write-Err "Not found: $BatPath"
        return $false
    }
    if (-not $WorkDir) { $WorkDir = Split-Path -Parent $BatPath }

    $display = Split-Path -Leaf $BatPath
    Write-Step "Running $display"
    Write-Host "      dir: $WorkDir" -ForegroundColor DarkGray
    Write-Host ''

    # ---------------------------------------------------------------------
    # PATH hygiene for the child batch (do this by hand: Start-Process has no
    # -Environment, so we set the variable for this process and its children).
    #
    # PROBLEM THIS SOLVES (observed 2026-10-03, pre-existing, unrelated to the
    # shortcuts): Git for Windows puts C:\Program Files\Git\usr\bin on PATH
    # AHEAD of C:\WINDOWS\System32. That directory ships GNU coreutils, so the
    # bare name `timeout` resolves to GNU timeout, not Windows' timeout.exe.
    # my_app's own start.bat calls `timeout /t 6 /nobreak`, and GNU timeout
    # rejects /t with "timeout: invalid time interval '/t'", after which cmd
    # reports '"and" was unexpected at this time' and start.bat exits 255 -
    # even though every service actually came up.
    #
    # Fixing it here (rather than editing start.bat) keeps the repo scripts
    # untouched and fixes it for every shortcut at once.
    # ---------------------------------------------------------------------
    $windowsDirs = @("$env:SystemRoot\System32", "$env:SystemRoot",
                     "$env:SystemRoot\System32\Wbem",
                     "$env:SystemRoot\System32\WindowsPowerShell\v1.0")
    $pathParts = $env:PATH -split ';' | Where-Object { $_ }
    # Drop every existing copy of the Windows directories...
    foreach ($wd in $windowsDirs) {
        $pathParts = $pathParts | Where-Object { $_ -ne $wd }
    }
    # ...then put them back at the FRONT, so System32 wins the lookup.
    $env:PATH = (($windowsDirs + $pathParts) -join ';')

    $startArgs = @{
        FilePath         = "$env:ComSpec"
        # Quote the path so a bat living under a directory with spaces is safe.
        ArgumentList     = @('/c', "`"$BatPath`"")
        WorkingDirectory = $WorkDir
        PassThru         = $true
        Wait             = $true
    }
    if ($Hidden) { $startArgs.WindowStyle = 'Hidden' }

    # NOTE: stdin is deliberately NOT redirected here.
    # `RedirectStandardInput` gives the child a pipe instead of a console, and
    # Windows' timeout.exe refuses to run without a console:
    #   "ERROR: Input redirection is not supported, exiting the process
    #    immediately."
    # my_app's start.bat waits with `timeout /t 6 /nobreak`, so redirecting
    # stdin makes that wait fail. Instead, the child inherits this controller's
    # console: each bat still gets its own window (Start-Process without
    # -NoNewWindow), its `pause` behaves normally, and `timeout` works.

    try {
        $proc = Start-Process @startArgs -ErrorAction Stop
        $rc = $proc.ExitCode
        Write-Host ''
        if ($rc -eq 0) {
            Write-Ok "$display finished (exit 0)."
        } else {
            Write-Warn "$display finished with exit code $rc - see its window output above."
        }
        return ($rc -eq 0)
    } catch {
        Write-Err "Could not run ${display}: $($_.Exception.Message)"
        return $false
    }
}

# The three nginx helpers live inside the nginx distribution directory, which
# MUST be the working directory: nginx resolves logs\nginx.pid relative to its
# own location (see AGENTS.md section 4 item 6b).
function Get-NginxBat { param([string]$Leaf) Join-Path $NginxDir $Leaf }

# ---------------------------------------------------------------------------
#  Command implementations
# ---------------------------------------------------------------------------

function Invoke-Status {
    Write-Head 'Service status'

    Write-Host 'Ports:' -ForegroundColor White
    $downCount = 0
    foreach ($port in $PortMap.Keys) {
        $portNum = [int]$port
        $label = $PortMap[$port]
        $up = Test-PortListening -Port $portNum
        if ($up) {
            Write-Host ("  {0,-5} {1,-40} " -f $portNum, $label) -NoNewline
            Write-Host 'LISTENING' -ForegroundColor Green
        } else {
            Write-Host ("  {0,-5} {1,-40} " -f $portNum, $label) -NoNewline
            Write-Host 'not listening' -ForegroundColor DarkGray
            $downCount++
        }
    }
    Write-Host ''

    # nginx needs one extra check: a listening port proves a master exists, but
    # the pid file is what the stop/reload signals will actually read.
    if (Test-Path $NginxDir) {
        $pidFile = Join-Path $NginxDir 'logs\nginx.pid'
        if (Test-Path $pidFile) {
            $nginxPid = (Get-Content -LiteralPath $pidFile -Raw -ErrorAction SilentlyContinue)
            if ($nginxPid) { $nginxPid = $nginxPid.Trim() }
            Write-Host "nginx master pid (logs\nginx.pid): $nginxPid"
        } else {
            Write-Host 'nginx master pid (logs\nginx.pid): absent - nginx is not running' -ForegroundColor DarkGray
        }
        Write-Host "nginx directory: $NginxDir"
    } else {
        Write-Warn "nginx directory missing: $NginxDir"
    }
    Write-Host ''

    Write-Host 'Entry points:' -ForegroundColor White
    Write-Host '  (port 80 redirects to HTTPS; the certificate is self-signed - a' -ForegroundColor DarkGray
    Write-Host '   browser "not trusted" warning is expected, not a fault)' -ForegroundColor DarkGray
    foreach ($entry in $EntryPoints) {
        Write-Host ("  {0,-38} {1}" -f $entry.Url, $entry.Name)
    }
    Write-Host ''

    if ($downCount -eq 0) {
        Write-Ok 'All 6 ports are listening - the full stack is up.'
    } else {
        Write-Warn "$downCount of $($PortMap.Count) ports are not listening."
        Write-Host '       Shortcuts 1/4/6 start nginx / my_app / portal respectively;' -ForegroundColor DarkGray
        Write-Host '       shortcut 8-start_all brings up all three in order.' -ForegroundColor DarkGray
    }
    Write-Host ''
}

function Invoke-StartNginx {
    Write-Head 'Start nginx'

    if (Test-PortListening -Port 80) {
        Write-Ok 'Port 80 is already listening - nginx is up, not starting a second instance.'
        Write-Host ''
        return
    }

    # start_nginx.bat itself re-checks the port and refuses to double-start;
    # this early exit is just to keep the common case quiet and fast.
    Invoke-ChildBat -BatPath (Get-NginxBat 'start_nginx.bat') -WorkDir $NginxDir | Out-Null
}

function Invoke-StopNginx {
    Write-Head 'Stop nginx'
    Write-Host 'The stop signal is issued from the nginx directory itself, so the' -ForegroundColor DarkGray
    Write-Host 'master pid is read from the right logs\nginx.pid (see AGENTS.md 4.6b).' -ForegroundColor DarkGray
    Write-Host ''
    Invoke-ChildBat -BatPath (Get-NginxBat 'stop_nginx.bat') -WorkDir $NginxDir | Out-Null
}

function Invoke-ReloadNginx {
    Write-Head 'Reload nginx'
    Write-Host 'Config is syntax-checked (nginx -t) first; the reload only happens' -ForegroundColor DarkGray
    Write-Host 'if the test passes, so a broken edit cannot take the site down.' -ForegroundColor DarkGray
    Write-Host ''
    Invoke-ChildBat -BatPath (Get-NginxBat 'reload_nginx.bat') -WorkDir $NginxDir | Out-Null
}

function Invoke-StartMyApp {
    Write-Head 'Start my_app'
    Write-Host 'backend 7038 + 7 worker groups + frontend 7090' -ForegroundColor DarkGray
    Write-Host ''
    Invoke-ChildBat -BatPath (Join-Path $MyAppDir 'start.bat') -WorkDir $MyAppDir | Out-Null
}

function Invoke-StopMyApp {
    Write-Head 'Stop my_app'
    Write-Host 'Stops every layer and writes backend\stopped.flag, which blocks the' -ForegroundColor DarkGray
    Write-Host 'logon autostart and the ensure task from quietly bringing it back.' -ForegroundColor DarkGray
    Write-Host 'The next start clears that flag automatically.' -ForegroundColor DarkGray
    Write-Host ''
    Invoke-ChildBat -BatPath (Join-Path $MyAppDir 'stop.bat') -WorkDir $MyAppDir | Out-Null
}

function Invoke-StartPortal {
    Write-Head 'Start portal'
    if (-not $PortalDir) {
        Write-Err 'Could not locate the portal directory (expected liberia-noc_soc-* under:'
        Write-Err "  $Root)"
        Write-Err 'Nothing started.'
        return
    }
    Write-Host 'portal 9267 + WhatsApp analysis service 9268' -ForegroundColor DarkGray
    Write-Host "dir: $PortalDir" -ForegroundColor DarkGray
    Write-Host ''
    Invoke-ChildBat -BatPath (Join-Path $PortalDir 'start.bat') -WorkDir $PortalDir | Out-Null
}

function Invoke-StopPortal {
    Write-Head 'Stop portal'
    if (-not $PortalDir) {
        Write-Err 'Could not locate the portal directory (expected liberia-noc_soc-* under:'
        Write-Err "  $Root)"
        Write-Err 'Nothing stopped.'
        return
    }
    Write-Host 'stops 9267 and 9268' -ForegroundColor DarkGray
    Write-Host "dir: $PortalDir" -ForegroundColor DarkGray
    Write-Host ''
    Invoke-ChildBat -BatPath (Join-Path $PortalDir 'stop.bat') -WorkDir $PortalDir | Out-Null
}

function Invoke-StartAll {
    Write-Head 'Start everything'
    Write-Host 'Order: my_app -> portal -> nginx' -ForegroundColor DarkGray
    Write-Host 'my_app and portal each pop their own report window; nginx runs quietly.' -ForegroundColor DarkGray
    Write-Host ''

    Write-Host '--- 1/3  my_app ---' -ForegroundColor White
    Invoke-ChildBat -BatPath (Join-Path $MyAppDir 'start.bat') -WorkDir $MyAppDir | Out-Null
    Write-Host ''

    Write-Host '--- 2/3  portal ---' -ForegroundColor White
    if ($PortalDir) {
        Invoke-ChildBat -BatPath (Join-Path $PortalDir 'start.bat') -WorkDir $PortalDir | Out-Null
    } else {
        Write-Err 'Portal directory not found - portal step skipped.'
    }
    Write-Host ''

    Write-Host '--- 3/3  nginx (silent) ---' -ForegroundColor White
    if (Test-PortListening -Port 80) {
        Write-Ok 'Port 80 already listening - nginx left as is.'
    } else {
        Invoke-ChildBat -BatPath (Get-NginxBat 'start_nginx.bat') -WorkDir $NginxDir -Hidden | Out-Null
    }
    Write-Host ''

    Invoke-Status
}

function Invoke-StopAll {
    Write-Head 'Stop everything'
    Write-Host 'Order: nginx -> portal -> my_app' -ForegroundColor DarkGray
    Write-Host '(nginx first so the entry points close before their upstreams go away)' -ForegroundColor DarkGray
    Write-Host ''

    Write-Host '--- 1/3  nginx ---' -ForegroundColor White
    if (Test-Path (Join-Path $NginxDir 'nginx.exe')) {
        Invoke-ChildBat -BatPath (Get-NginxBat 'stop_nginx.bat') -WorkDir $NginxDir | Out-Null
    } else {
        Write-Warn "nginx directory missing: $NginxDir"
    }
    Write-Host ''

    Write-Host '--- 2/3  portal ---' -ForegroundColor White
    if ($PortalDir) {
        Invoke-ChildBat -BatPath (Join-Path $PortalDir 'stop.bat') -WorkDir $PortalDir | Out-Null
    } else {
        Write-Err 'Portal directory not found - portal step skipped.'
    }
    Write-Host ''

    Write-Host '--- 3/3  my_app ---' -ForegroundColor White
    Invoke-ChildBat -BatPath (Join-Path $MyAppDir 'stop.bat') -WorkDir $MyAppDir | Out-Null
    Write-Host ''

    Write-Host 'NOTE: nginx is watched by the Nginx_EnsureRunning scheduled task, which' -ForegroundColor Yellow
    Write-Host '      probes port 80 every 5 minutes and will bring it back up. Disable' -ForegroundColor Yellow
    Write-Host '      that task first if you need nginx to stay down.' -ForegroundColor Yellow
    Write-Host ''
    Write-Host 'my_app wrote backend\stopped.flag - autostart and the ensure task will' -ForegroundColor Yellow
    Write-Host 'not restart it. The next 4-start_myapp clears that flag.' -ForegroundColor Yellow
    Write-Host ''

    Invoke-Status
}

# ---------------------------------------------------------------------------
#  Dispatch
# ---------------------------------------------------------------------------

# Accept several spellings so a shortcut's argument and a hand-typed command
# both work ("1", "1-start_nginx", "1-start-nginx").
$normalized = $Command.Trim().ToLowerInvariant()
switch -Regex ($normalized) {
    '^0([-_].*)?$|^status$'                { Invoke-Status;      break }
    '^1([-_].*)?$|^(start[-_]?)?nginx$'    { Invoke-StartNginx;  break }
    '^2([-_].*)?$|^stop[-_]?nginx$'        { Invoke-StopNginx;   break }
    '^3([-_].*)?$|^reload[-_]?nginx$'      { Invoke-ReloadNginx; break }
    '^4([-_].*)?$|^start[-_]?myapp$'       { Invoke-StartMyApp;  break }
    '^5([-_].*)?$|^stop[-_]?myapp$'        { Invoke-StopMyApp;   break }
    '^6([-_].*)?$|^start[-_]?portal$'      { Invoke-StartPortal; break }
    '^7([-_].*)?$|^stop[-_]?portal$'       { Invoke-StopPortal;  break }
    '^8([-_].*)?$|^start[-_]?all$'         { Invoke-StartAll;    break }
    '^9([-_].*)?$|^stop[-_]?all$'          { Invoke-StopAll;     break }
    default {
        Write-Err "Unknown command: '$Command'"
        Write-Host ''
        Write-Host 'Valid commands:'
        Write-Host '  0-status        1-start-nginx   2-stop-nginx    3-reload-nginx'
        Write-Host '  4-start-myapp   5-stop-myapp    6-start-portal  7-stop-portal'
        Write-Host '  8-start-all     9-stop-all'
        Write-Host ''
    }
}

Write-Host ''
Write-Host 'Press any key to close this window (services keep running).' -ForegroundColor White
try {
    # ReadKey needs an attached interactive console. When the script is driven
    # by a scheduled task, a pipe, or an automation harness there is no console
    # to read from - ReadKey would either throw or block forever. Test first.
    if ([Environment]::UserInteractive -and -not [Console]::IsInputRedirected) {
        # $null = ... keeps the pressed key from being echoed into the window.
        $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
    } else {
        Write-Host '(no interactive console - not waiting for a key)' -ForegroundColor DarkGray
    }
} catch {
    Write-Host '(could not read a key - not waiting)' -ForegroundColor DarkGray
}
