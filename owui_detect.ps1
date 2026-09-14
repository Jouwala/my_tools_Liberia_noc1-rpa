# owui_detect.ps1
# Read-only reconnaissance for the Open WebUI instance on this machine.
# Target host: 192.168.100.27 (port 3000, Open WebUI 0.11.3)
#
# Run ON 192.168.100.27 (via RDP):
#   powershell -ExecutionPolicy Bypass -File .\owui_detect.ps1
#
# This script changes NOTHING. It only reports.
# Paste the full output back so the exact fix can be generated.

$ErrorActionPreference = 'SilentlyContinue'
$ProgressPreference    = 'SilentlyContinue'

function H($t) { Write-Host ""; Write-Host ("===== " + $t + " =====") }

H "1. Host"
Write-Host ("ComputerName : " + $env:COMPUTERNAME)
Write-Host ("User         : " + $env:USERNAME)
Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.IPAddress -notlike '127.*' } |
    ForEach-Object { Write-Host ("IPv4         : " + $_.IPAddress) }

H "2. Who owns port 3000"
$conns = Get-NetTCPConnection -LocalPort 3000 -State Listen
if ($conns) {
    foreach ($c in $conns) {
        $ci = Get-CimInstance Win32_Process -Filter ("ProcessId=" + $c.OwningProcess)
        Write-Host ("PID        : " + $c.OwningProcess)
        Write-Host ("LocalAddr  : " + $c.LocalAddress + ":" + $c.LocalPort)
        Write-Host ("Process    : " + $ci.Name)
        Write-Host ("ExePath    : " + $ci.ExecutablePath)
        Write-Host ("CommandLine: " + $ci.CommandLine)
    }
} else {
    Write-Host "No listener on TCP 3000 (is Open WebUI stopped?)"
}

H "3. Docker"
$dk = Get-Command docker -ErrorAction SilentlyContinue
if ($dk) {
    Write-Host ("docker: " + $dk.Source)
    Write-Host "--- docker ps -a ---"
    docker ps -a --format "{{.ID}}|{{.Image}}|{{.Names}}|{{.Status}}|{{.Ports}}" 2>&1
    Write-Host "--- docker compose projects ---"
    docker compose ls 2>&1
} else {
    Write-Host "docker CLI not found -> likely a native (non-container) install"
}

H "4. Services and processes matching webui"
Get-CimInstance Win32_Service |
    Where-Object { $_.Name -match 'webui|open-webui' -or $_.DisplayName -match 'webui' -or $_.PathName -match 'webui' } |
    Select-Object Name, DisplayName, State, StartMode, PathName | Format-List

Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -match 'open[-_ ]?webui|uvicorn' } |
    Select-Object ProcessId, Name, ExecutablePath, CommandLine | Format-List

H "5. Environment variables (persisted)"
foreach ($scope in 'Machine', 'User') {
    foreach ($n in 'WEBUI_AUTH', 'DATA_DIR', 'WEBUI_SECRET_KEY', 'WEBUI_URL') {
        $v = [Environment]::GetEnvironmentVariable($n, $scope)
        if ($v) { Write-Host ("{0,-8} {1,-18} = {2}" -f $scope, $n, $v) }
    }
}
Write-Host "(blank = not set at that scope)"

H "6. Candidate data dirs and webui.db"
$cands = @(
    "$env:LOCALAPPDATA\open-webui",
    "$env:APPDATA\open-webui",
    "$env:USERPROFILE\.open-webui",
    "$env:ProgramData\open-webui",
    "C:\open-webui",
    "D:\open-webui",
    "C:\open-webui\backend\data"
)
foreach ($d in $cands) {
    if (Test-Path $d) {
        Write-Host ("DIR  : " + $d)
        Get-ChildItem $d -Filter *.db -Recurse -Depth 2 |
            ForEach-Object { Write-Host ("   db : {0}  {1} bytes  {2}" -f $_.FullName, $_.Length, $_.LastWriteTime) }
    }
}
if ($env:DATA_DIR) {
    Write-Host ("DATA_DIR target: " + $env:DATA_DIR)
    Get-ChildItem $env:DATA_DIR -Filter *.db -Recurse -Depth 2 |
        ForEach-Object { Write-Host ("   db : {0}  {1} bytes  {2}" -f $_.FullName, $_.Length, $_.LastWriteTime) }
}

H "7. Deployment dirs holding compose / start scripts"
$roots = @("C:\", "D:\") | Where-Object { Test-Path $_ }
foreach ($r in $roots) {
    Get-ChildItem $r -Directory -Depth 1 |
        Where-Object { $_.Name -match 'open.?webui' } |
        ForEach-Object { Write-Host ("DIR  : " + $_.FullName) }
}
Get-ChildItem "C:\","D:\" -Include 'docker-compose*.yml','docker-compose*.yaml','.env','start*.bat','start*.ps1','start*.sh' -Recurse -Depth 3 |
    Where-Object { $_.FullName -match 'webui' } |
    ForEach-Object { Write-Host ("FILE : " + $_.FullName) }

H "8. Live API self-check"
try {
    $r = Invoke-RestMethod -Uri "http://127.0.0.1:3000/api/config" -TimeoutSec 8
    Write-Host ("version       = " + $r.version)
    Write-Host ("features.auth = " + $r.features.auth)
    Write-Host ("enable_signup = " + $r.features.enable_signup)
    Write-Host ("enable_login  = " + $r.features.enable_login_form)
} catch {
    Write-Host ("API check failed: " + $_.Exception.Message)
}

H "9. Done"
Write-Host "Nothing was modified. Paste this whole output back."
