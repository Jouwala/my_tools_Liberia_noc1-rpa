# start_hidden.ps1 - Hidden startup of the liberia-noc_soc portal + its companion
# WhatsApp local analysis service (the one the portal page calls on localhost:9268).
#
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File start_hidden.ps1
#       Start whatever is missing, write log\start_hidden_result.txt, popup on problems.
#   powershell -NoProfile -ExecutionPolicy Bypass -File start_hidden.ps1 -Quiet
#       No popup, and respect stopped.flag written by stop.bat (for a future autostart task).
#
# NOTE: keep this file ASCII-only. PowerShell 5.1 reads BOM-less .ps1 as ANSI,
# so non-ASCII text here can be garbled and break parsing on another box.
param(
    [switch]$Quiet
)
$ErrorActionPreference = 'Continue'
$base = Split-Path -Parent $MyInvocation.MyCommand.Definition
$logDir = Join-Path $base 'log'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
$resultFile = Join-Path $logDir 'start_hidden_result.txt'
$flag = Join-Path $base 'stopped.flag'
$waDir = Join-Path $base 'scripts\whatsapp_analysis'

$report = [System.Collections.Generic.List[string]]::new()
$script:failCount = 0
$script:warnCount = 0

function Add-Report([string]$line) { $script:report.Add($line) }

function Test-PortListening([int]$port) {
    return ($null -ne (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue))
}

function Get-PortOwnerPid([int]$port) {
    $c = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($c) { return [int]$c.OwningProcess }
    return 0
}

# Is the process holding the port really one of ours? Guards against the classic
# false OK: some unrelated program sits on 9267/9268 and the portal page silently
# talks to the wrong thing.
function Test-OwnedByProject([int]$procId, [string]$needle) {
    if ($procId -le 0) { return $false }
    try {
        $p = Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction Stop
        return [bool]($p.CommandLine -and ($p.CommandLine -like ("*" + $needle + "*")))
    } catch { return $false }
}

# Priority hygiene for the processes this script owns.
#
# Why this exists (2026-09-21): this script is launched by the Task Scheduler task
# "Portal_EnsureRunning". A task whose XML has no <Priority> element starts its
# processes at BELOW_NORMAL (Task Scheduler default 7), and everything the task
# spawns inherits that class. Result: the portal dev server (9267) and the WhatsApp
# service (9268) ran at BelowNormal while nginx / my_app / anything started by hand
# ran at Normal. On this box (28 logical CPUs, ~10 agents + browsers competing,
# only ~3 GB free RAM) a BelowNormal process gets starved for seconds to minutes:
# measured 2.3 s ... 113.7 s with NO response on /uniplam/api/*, while TCP connect
# still completed in 0.4 ms and a Normal-priority Node server answered in 1 ms.
# The page load then shows one request "taking 23 s" - it is only the victim.
# Windows also trims low-priority working sets first (the dev server sat at 52 MB
# of a 194 MB private set), which adds hard page faults on top.
#
# Setting the real listener back to Normal is idempotent and needs no admin, and
# because this script runs every 5 minutes it also self-heals a service that an
# older run (or a manual start) left at BelowNormal.
function Set-ServicePriority([int]$port, [string]$label) {
    $procId = Get-PortOwnerPid $port
    if ($procId -le 0) { return }
    try {
        $p = Get-Process -Id $procId -ErrorAction Stop
        $before = $p.PriorityClass
        if ($before -eq [System.Diagnostics.ProcessPriorityClass]::Normal) {
            Add-Report ("[OK] {0}: pid={1} priority is Normal" -f $label, $procId)
            return
        }
        $p.PriorityClass = [System.Diagnostics.ProcessPriorityClass]::Normal
        Add-Report ("[*] {0}: pid={1} priority {2} -> Normal (a scheduled-task child inherits BelowNormal, which starves it on a busy box)" -f $label, $procId, $before)
    } catch {
        Add-Report ("[WARN] {0}: cannot raise priority of pid={1}: {2}" -f $label, $procId, $_.Exception.Message)
        $script:warnCount++
    }
}

function Wait-Port([int]$port, [int]$seconds) {
    for ($i = 0; $i -lt $seconds; $i++) {
        if (Test-PortListening $port) { return $true }
        Start-Sleep -Seconds 1
    }
    return (Test-PortListening $port)
}

# Returns the HTTP status code, or 0 when the request failed.
function Test-Http([string]$url, [int]$timeoutSec) {
    try {
        $r = Invoke-WebRequest -Uri $url -TimeoutSec $timeoutSec -UseBasicParsing -ErrorAction Stop
        return [int]$r.StatusCode
    } catch {
        return 0
    }
}

# Port open is not the same as "the service works", so every start is confirmed
# with a real HTTP call before it is reported as OK.
function Confirm-Http([string]$label, [int]$port, [string]$url) {
    $code = Test-Http $url 10
    if ($code -eq 200) {
        Add-Report ("[OK] {0} started on port {1} ({2} responded 200)" -f $label, $port, $url)
        return $true
    }
    Add-Report ("[WARN] {0} port {1} is listening but {2} did not answer 200 (got {3}), check the log" -f $label, $port, $url, $code)
    $script:warnCount++
    return $true
}

# Launch a service detached + hidden, redirecting its output to log\<logName>.
# Returns $true when the process was created.
function Start-Hidden {
    param($exe, $argList, $workDir, $logName)
    $log = Join-Path $logDir $logName
    $err = "$log.err"
    try {
        Start-Process -FilePath $exe -ArgumentList $argList -WorkingDirectory $workDir `
            -WindowStyle Hidden -RedirectStandardOutput $log -RedirectStandardError $err -ErrorAction Stop
        return $true
    } catch {
        if ($_.Exception.Message -notmatch 'already been added') {
            Add-Report ("[FAIL] Cannot launch {0}: {1}" -f $logName, $_.Exception.Message)
            return $false
        }
        # Windows PowerShell 5.1 bug: when the environment contains two variables
        # that differ only in case (e.g. http_proxy AND HTTP_PROXY, which a proxy
        # setup or a shell profile can leave behind), Start-Process with
        # -RedirectStandardOutput throws
        #   "Item has already been added. Key in dictionary: 'http_proxy'".
        # Dropping the lower-case duplicates works around it and is harmless for a
        # local dev server, so it is retried instead of failing the whole start.
        foreach ($k in @('http_proxy', 'https_proxy', 'no_proxy', 'all_proxy')) {
            [System.Environment]::SetEnvironmentVariable($k, $null)
        }
        try {
            Start-Process -FilePath $exe -ArgumentList $argList -WorkingDirectory $workDir `
                -WindowStyle Hidden -RedirectStandardOutput $log -RedirectStandardError $err -ErrorAction Stop
            Add-Report '[*] Note: dropped duplicate lower-case proxy env vars to work around a PowerShell 5.1 Start-Process bug.'
            return $true
        } catch {
            Add-Report ("[FAIL] Cannot launch {0}: {1}" -f $logName, $_.Exception.Message)
            return $false
        }
    }
}

$header = "===== portal start_hidden report {0} PORTAL_START_V1 (Quiet={1}) =====" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Quiet
Add-Report $header

# Stop marker: stop.bat writes it, this script (non-Quiet) clears it.
if ($Quiet -and (Test-Path $flag)) {
    Add-Report '[SKIP] stopped.flag detected: services were stopped by stop.bat. Skipping startup.'
    Add-Report '       Run start.bat to restart.'
    ($report | Where-Object { $_ }) | Set-Content -Path $resultFile -Encoding UTF8
    exit 0
}
if (-not $Quiet -and (Test-Path $flag)) {
    try { Remove-Item $flag -Force -ErrorAction Stop } catch { }
}

# ---------- toolchain ----------
$npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $npm) { $npm = Get-Command npm -ErrorAction SilentlyContinue }
$nodeExe = (Get-Command node.exe -ErrorAction SilentlyContinue).Source
if (-not $npm -and -not $nodeExe) {
    Add-Report '[FAIL] Neither npm nor node found in PATH, cannot start anything'
    $script:failCount++
    $report | Set-Content -Path $resultFile -Encoding UTF8
    exit 2
}

# ---------- 1) Portal dev server (vite, 9267) ----------
Add-Report '----- 1) Portal dev server (9267) -----'
function Ensure-Portal {
    if (Test-PortListening 9267) {
        $owner = Get-PortOwnerPid 9267
        if (Test-OwnedByProject $owner 'liberia-noc_soc') {
            Add-Report ("[OK] Portal dev server already running (pid={0}, port 9267)" -f $owner)
            return $true
        }
        Add-Report ("[WARN] Port 9267 is held by pid={0}, which is NOT this project - the portal will not be reachable as expected." -f $owner)
        Add-Report '       Run stop.bat first (it kills by port), then start.bat.'
        $script:warnCount++
        return $false
    }
    # 1st attempt: the project's own script (npm run dev).
    if ($npm) {
        if ((Start-Hidden $npm.Source @('run', 'dev') $base 'portal_dev.log') -and (Wait-Port 9267 60)) {
            return (Confirm-Http 'Portal dev server' 9267 'http://127.0.0.1:9267/uniplam/')
        }
        Add-Report '[WARN] npm run dev did not open port 9267'
        $script:warnCount++
    }
    # 2nd attempt: bypass npm and run the vite CLI with node directly. npm's
    # PATH shim for node_modules\.bin can fail ("'vite' is not recognized as an
    # internal or external command"), and without this the portal would just
    # stay down.
    $viteJs = Join-Path $base 'node_modules\vite\bin\vite.js'
    if ($nodeExe -and (Test-Path $viteJs)) {
        Add-Report '[*] Retrying with: node node_modules\vite\bin\vite.js --port=9267'
        if ((Start-Hidden $nodeExe @($viteJs, '--port=9267', '--host=0.0.0.0') $base 'portal_dev.log') -and (Wait-Port 9267 60)) {
            return (Confirm-Http 'Portal dev server' 9267 'http://127.0.0.1:9267/uniplam/')
        }
    }
    Add-Report '[FAIL] Portal dev server did not listen on 9267, check log\portal_dev.log and log\portal_dev.log.err'
    $script:failCount++
    return $false
}
$portalOk = Ensure-Portal
# See Set-ServicePriority: without this the dev server stays at BelowNormal (inherited
# from the Portal_EnsureRunning scheduled task) and the portal API stalls for tens of
# seconds whenever the machine is busy. Runs on every 5-minute task tick.
Set-ServicePriority 9267 'Portal dev server (9267)'

# ---------- 2) WhatsApp local analysis service (9268) ----------
# This is the service the portal page calls directly from the browser at
# http://localhost:9268; when it is down the page shows
# "cannot connect to the local analysis service".
Add-Report '----- 2) WhatsApp local analysis service (9268) -----'

# Health probe: /api/health is public and returns {"status":"ok",...}.
# Do NOT use /api/tasks for the health check - it requires auth and answers 401
# without a token, so a 200 test there can never pass and produces false warnings.
function Test-WaHealthy {
    try {
        $r = Invoke-WebRequest -Uri 'http://127.0.0.1:9268/api/health' -TimeoutSec 10 -UseBasicParsing -ErrorAction Stop
        return ([string]$r.Content -match '"status"\s*:\s*"ok"')
    } catch {
        return $false
    }
}

function Ensure-WhatsApp {
    if (Test-PortListening 9268) {
        # Trust a real HTTP health check over process-cmdline matching. On Windows a
        # dual-stack listener can make Get-NetTCPConnection report the wrong owner
        # (e.g. the portal's vite process), which used to raise a false
        # "NOT the WhatsApp analysis service" warning even though the service was
        # up and serving /api/health on 9268.
        if (Test-WaHealthy) {
            $owner = Get-PortOwnerPid 9268
            Add-Report ("[OK] WhatsApp analysis service already running on port 9268 (pid={0}, /api/health ok)" -f $owner)
            return $true
        }
        # Health check failed: fall back to the ownership test to tell whether the
        # port is held by our (unhealthy) service or by an unrelated program.
        $owner = Get-PortOwnerPid 9268
        if (Test-OwnedByProject $owner 'whatsapp_analysis') {
            Add-Report ("[WARN] WhatsApp analysis port 9268 is listening (owner pid={0}) but /api/health did not return status ok" -f $owner)
            $script:warnCount++
            return $true
        }
        Add-Report ("[WARN] Port 9268 is held by pid={0}, which is NOT the WhatsApp analysis service." -f $owner)
        Add-Report '       Run stop.bat first (it kills by port), then start.bat.'
        $script:warnCount++
        return $false
    }
    if (-not (Test-Path $waDir)) {
        Add-Report ("[FAIL] WhatsApp analysis directory not found: {0}" -f $waDir)
        $script:failCount++
        return $false
    }
    # 1st attempt: "npm start" = tsx server/index.ts (no watch mode). Deliberately
    # NOT "npm run dev": tsx watch would respawn the child right after stop.bat
    # kills it, so the port would come back a second later.
    if ($npm) {
        if ((Start-Hidden $npm.Source @('start') $waDir 'whatsapp_analysis.log') -and (Wait-Port 9268 60)) {
            if (Test-WaHealthy) {
                Add-Report '[OK] WhatsApp analysis service started on port 9268 (/api/health ok)'
                return $true
            }
            Add-Report '[WARN] WhatsApp analysis port 9268 opened but /api/health did not return status ok'
            $script:warnCount++
            return $true
        }
        Add-Report '[WARN] npm start did not open port 9268'
        $script:warnCount++
    }
    # 2nd attempt: bypass npm, run the tsx CLI with node directly.
    $tsxCli = Join-Path $waDir 'node_modules\tsx\dist\cli.mjs'
    if ($nodeExe -and (Test-Path $tsxCli)) {
        Add-Report '[*] Retrying with: node scripts\whatsapp_analysis\node_modules\tsx\dist\cli.mjs server/index.ts'
        if ((Start-Hidden $nodeExe @($tsxCli, 'server/index.ts') $waDir 'whatsapp_analysis.log') -and (Wait-Port 9268 60)) {
            if (Test-WaHealthy) {
                Add-Report '[OK] WhatsApp analysis service started on port 9268 (/api/health ok)'
                return $true
            }
            Add-Report '[WARN] WhatsApp analysis port 9268 opened but /api/health did not return status ok'
            $script:warnCount++
            return $true
        }
    }
    Add-Report '[FAIL] WhatsApp analysis service did not listen on 9268, check log\whatsapp_analysis.log and log\whatsapp_analysis.log.err'
    $script:failCount++
    return $false
}
$waOk = Ensure-WhatsApp
# Same BelowNormal-inheritance problem as the portal dev server - see Set-ServicePriority.
Set-ServicePriority 9268 'WhatsApp analysis service (9268)'

# ======================================================================
# Summary: write result file + popup (only when something needs attention)
# ======================================================================
$failCount = $script:failCount
$warnCount = $script:warnCount
$footer = "===== Result: {0} failures / {1} warnings =====`r`nFull log: {2}" -f $failCount, $warnCount, $resultFile
$all = New-Object System.Collections.Generic.List[string]
$all.Add($header)
foreach ($l in $report) { if ($l -ne $header) { $all.Add($l) } }
$all.Add($footer)
$all | Set-Content -Path $resultFile -Encoding UTF8

foreach ($l in $all) { Write-Host $l }

if ((-not $Quiet) -and ($failCount -gt 0 -or $warnCount -gt 0)) {
    try {
        Add-Type -AssemblyName System.Windows.Forms | Out-Null
        $icon = [System.Windows.Forms.MessageBoxIcon]::Information
        if ($failCount -gt 0) { $icon = [System.Windows.Forms.MessageBoxIcon]::Error }
        elseif ($warnCount -gt 0) { $icon = [System.Windows.Forms.MessageBoxIcon]::Warning }
        [System.Windows.Forms.MessageBox]::Show(
            ($all -join "`r`n"),
            'Portal Startup Result',
            [System.Windows.Forms.MessageBoxButtons]::OK,
            $icon) | Out-Null
    } catch { }
}

if ($failCount -gt 0) { exit 1 }
exit 0
