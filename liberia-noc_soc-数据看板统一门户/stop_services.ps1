# stop_services.ps1 - stop the liberia-noc_soc portal and its companion
#                     WhatsApp local analysis service.
#
# Ports: 9267 = portal dev server (vite)
#        9268 = WhatsApp analysis service (scripts\whatsapp_analysis)
#
# Called by stop.bat. Kept in PowerShell (not inline in the .bat) because the
# logic needs the process tree: "tsx watch" / npm wrappers respawn their child,
# so killing only the port owner is not enough.
#
# Layers:
#   1. command-line sweep: find our own node processes, walk UP to the top-most
#      node ancestor and tree-kill it (that takes the respawner with it)
#   2. kill by port WITH /T as a backstop (catches a listener that does not
#      match the command-line pattern)
#   3. verify both ports released, report leftovers
#   4. write stopped.flag (a -Quiet start skips until start.bat clears it)
#   5. if anything survived, re-run elevated (UAC) - a process started by an
#      elevated task cannot be killed from a normal shell
#
# NOTE: keep this file ASCII-only (PowerShell 5.1 reads BOM-less .ps1 as ANSI).
param(
    [switch]$Quiet
)
$ErrorActionPreference = 'Continue'
$base = Split-Path -Parent $MyInvocation.MyCommand.Definition
$logDir = Join-Path $base 'log'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
$resultFile = Join-Path $logDir 'stop_result.txt'
$flag = Join-Path $base 'stopped.flag'
$ports = @(9267, 9268)
# Specific to this project: the WhatsApp service dir, or the portal's own
# node_modules (covers the vite dev server). Unrelated node processes survive.
$pat = 'whatsapp_analysis|liberia-noc_soc[^\\/]*\\node_modules'

$report = [System.Collections.Generic.List[string]]::new()
$script:failCount = 0

function Add-Report([string]$line) { $script:report.Add($line) }

function Test-PortListening([int]$port) {
    return ($null -ne (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue))
}

function Get-PortOwnerPid([int]$port) {
    $c = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($c) { return [int]$c.OwningProcess }
    return 0
}

function Stop-Tree([int]$procId) {
    if ($procId -le 0) { return }
    taskkill /PID $procId /T /F 2>$null | Out-Null
}

$header = "===== portal stop_services report {0} PORTAL_STOP_V1 (Quiet={1}) =====" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Quiet
Add-Report $header

# ---------- 1) Sweep: our node processes, tree-killed from their top node ancestor ----------
Add-Report '----- 1) Process sweep -----'
$all = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue
$byId = @{}
foreach ($p in $all) { $byId[[int]$p.ProcessId] = $p }

$hits = @($all | Where-Object { $_.Name -eq 'node.exe' -and $_.CommandLine -match $pat -and $_.ProcessId -ne $PID })
$roots = @()
foreach ($h in $hits) {
    $cur = [int]$h.ProcessId
    for ($i = 0; $i -lt 10; $i++) {
        $p = $byId[$cur]
        if (-not $p) { break }
        $par = $byId[[int]$p.ParentProcessId]
        if (-not $par) { break }
        if ($par.Name -eq 'node.exe' -and ($par.CommandLine -match $pat -or $par.CommandLine -match 'npm-cli\.js')) {
            $cur = [int]$par.ProcessId
        } else {
            break
        }
    }
    $roots += $cur
}
$roots = @($roots | Sort-Object -Unique)

if ($roots.Count -eq 0) {
    Add-Report '[OK] No portal / WhatsApp node process found.'
} else {
    foreach ($r in $roots) {
        $cmd = [string]$byId[$r].CommandLine
        if ($cmd.Length -gt 150) { $cmd = $cmd.Substring(0, 150) + '...' }
        Stop-Tree $r
        Add-Report ("[*] Killed node tree PID={0} : {1}" -f $r, $cmd)
    }
    Start-Sleep -Seconds 1
}

# ---------- 2) Kill by port as a backstop ----------
Add-Report '----- 2) Port check / backstop -----'
foreach ($port in $ports) {
    $owner = Get-PortOwnerPid $port
    if ($owner -le 0) {
        Add-Report ("[OK] Port {0}: nothing listening" -f $port)
        continue
    }
    Stop-Tree $owner
    Start-Sleep -Milliseconds 800
    if (Test-PortListening $port) {
        $again = Get-PortOwnerPid $port
        Add-Report ("[WARN] Port {0} still held by pid={1} after tree kill (pid may differ: {2})" -f $port, $owner, $again)
    } else {
        Add-Report ("[*] Killed listener on port {0} (pid={1})" -f $port, $owner)
    }
}

# ---------- 3) Verify ----------
Add-Report '----- 3) Verification -----'
$left = @()
foreach ($port in $ports) {
    if (Test-PortListening $port) { $left += $port }
}
if ($left.Count -eq 0) {
    Add-Report '[OK] All portal ports released (9267, 9268).'
} else {
    Add-Report ("[FAIL] Still listening: {0}" -f (($left | ForEach-Object { ":" + $_ }) -join ' '))
    $script:failCount++
}

# ---------- 4) Stop marker ----------
$stamp = "{0} stopped by {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $env:USERNAME
$stamp | Set-Content -Path $flag -Encoding UTF8
Add-Report '[OK] Wrote stopped.flag - a -Quiet start will skip until start.bat clears it.'

# ---------- 5) Summary (+ elevated retry when something survived) ----------
$failCount = $script:failCount
$footer = "===== Result: {0} failures =====`r`nFull log: {1}" -f $failCount, $resultFile
$allLines = New-Object System.Collections.Generic.List[string]
$allLines.Add($header)
foreach ($l in $report) { if ($l -ne $header) { $allLines.Add($l) } }
$allLines.Add($footer)
$allLines | Set-Content -Path $resultFile -Encoding UTF8
foreach ($l in $allLines) { Write-Host $l }

if ($failCount -eq 0) {
    Write-Host '[*] Portal and WhatsApp analysis service stopped.'
    exit 0
}

# Something survived: it is probably owned by an elevated task, which a normal
# shell cannot kill. Re-run this script elevated, unless we already are.
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($isAdmin) {
    Write-Host '[FAIL] Some processes could not be stopped even as administrator - check the list above.'
    exit 1
}
Write-Host '[*] Some processes need administrator rights to stop.'
Write-Host '    Retrying with elevation - please click "Yes" on the UAC prompt.'
try {
    Start-Process -FilePath 'powershell.exe' `
        -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $MyInvocation.MyCommand.Definition) `
        -Verb RunAs -Wait
} catch {
    Write-Host ('[FAIL] Elevated retry failed: ' + $_.Exception.Message)
}
exit 0
