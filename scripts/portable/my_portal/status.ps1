<#
  status.ps1 - read-only health check for the OLBR portable copy.
  Ports come from the copy root .env; nothing here starts or stops a service.
  "LISTEN" only means something holds the port. On the source machine the
  production instance may hold it. The copy-managed pid files are the only
  reliable evidence that a process belongs to THIS copy.
#>
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$envFile = Join-Path $Root '.env'
$cfg = @{}
if (Test-Path -LiteralPath $envFile) {
    foreach ($line in [System.IO.File]::ReadAllLines($envFile)) {
        $t = $line.Trim()
        if (-not $t -or $t.StartsWith('#')) { continue }
        $i = $t.IndexOf('=')
        if ($i -lt 1) { continue }
        $cfg[$t.Substring(0, $i).Trim()] = $t.Substring($i + 1).Trim()
    }
} else {
    Write-Warning "Copy root .env not found: $envFile (using default ports)"
}

function Get-Port([string]$Key, [string]$Default) {
    $v = $cfg[$Key]
    if ($v -and $v -match '^\d+$') { return [int]$v }
    return [int]$Default
}

$targets = @(
    @{ n = 'nginx HTTP';    p = (Get-Port 'NGINX_HTTP_PORT'    '80')    },
    @{ n = 'nginx HTTPS';   p = (Get-Port 'NGINX_HTTPS_PORT'   '443')   },
    @{ n = 'my_app backend';p = (Get-Port 'MY_APP_BE_PORT'     '7038')  },
    @{ n = 'my_app front';  p = (Get-Port 'MY_APP_FE_PORT'     '7090')  },
    @{ n = 'unified portal';p = (Get-Port 'PORTAL_PORT'        '9267')  },
    @{ n = 'WA analysis';   p = (Get-Port 'WA_ANALYSIS_PORT'   '9268')  },
    @{ n = 'QA / bot HTTP'; p = (Get-Port 'QA_HTTP_PORT'       '9269')  },
    @{ n = 'portable PG';   p = (Get-Port 'PGPORT'             '55432') }
)

Write-Host ''
Write-Host 'OLBR portable copy - status' -ForegroundColor Cyan
Write-Host "Root: $Root"
Write-Host ('-' * 52)
Write-Host ('{0,-7} {1,-18} {2,-8}' -f 'PORT', 'SERVICE', 'LISTEN') -ForegroundColor DarkGray
foreach ($t in $targets) {
    $state = '-'
    $cli = New-Object System.Net.Sockets.TcpClient
    try {
        $iar = $cli.BeginConnect('127.0.0.1', [int]$t.p, $null, $null)
        if ($iar.AsyncWaitHandle.WaitOne(300, $false)) {
            $cli.EndConnect($iar)
            $state = 'LISTEN'
        }
    } catch { $state = '-' }
    finally { try { $cli.Close() } catch { } }
    $color = if ($state -eq 'LISTEN') { 'Green' } else { 'DarkGray' }
    Write-Host ('{0,-7} {1,-18} {2,-8}' -f $t.p, $t.n, $state) -ForegroundColor $color
}

Write-Host ''
$tmpDir = Join-Path $Root 'TMP'
$pf = @(Get-ChildItem -LiteralPath $tmpDir -Filter 'portable-*.pid' -File -ErrorAction SilentlyContinue)
if ($pf.Count -gt 0) {
    Write-Host 'Started by THIS copy (pid files in TMP\):' -ForegroundColor Cyan
    foreach ($p in $pf) { Write-Host ('  - ' + $p.BaseName) }
} else {
    Write-Host 'No portable-*.pid files - this copy has no tracked running services.'
}
Write-Host ''
Write-Host 'NOTE: LISTEN does not prove ownership. On the source machine the' -ForegroundColor Yellow
Write-Host '      production instance may hold 80/443/7038/7090/9267.' -ForegroundColor Yellow
$hPort = Get-Port 'NGINX_HTTPS_PORT' '443'
$suffix = if ([int]$hPort -eq 443) { '' } else { ":$hPort" }
$base = "https://localhost$suffix"
Write-Host ''
Write-Host "Entry: $base/   (self-signed cert warning is expected)"
Write-Host "       $base/myapp/"
Write-Host "       $base/uniplam/"
Write-Host "       $base/v3/olbrportal/"
