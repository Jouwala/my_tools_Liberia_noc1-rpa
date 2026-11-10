<#
  make_desktop_shortcuts.ps1 - create real .lnk shortcuts for THIS copy.

  Run it on the TARGET machine (double-click 8-install-desktop-shortcuts.bat).
  The absolute paths are generated at run time from $PSScriptRoot, so unlike a
  packed .lnk they stay correct after changing the drive letter or folder name.

  Safety: defaults to a separate desktop folder "my_portal_portable" so the
  existing desktop "my_portal" (production instance) is never overwritten.
  Use -FolderName my_portal -Force only if you really want to replace it.
#>
[CmdletBinding()]
param(
    [string]$FolderName = 'my_portal_portable',
    [switch]$Force
)
$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$Desktop = [Environment]::GetFolderPath('Desktop')
if (-not (Test-Path -LiteralPath $Desktop)) { throw "Desktop folder not found: $Desktop" }
$OutDir = Join-Path $Desktop $FolderName

if ($Root -match '[^\x00-\x7F]') {
    Write-Warning "The copy path contains non-ASCII characters: $Root"
    Write-Warning 'On a Windows-1252 ANSI codepage a .lnk may store them incorrectly.'
    Write-Warning 'If a shortcut fails, double-click the .bat inside my_portal\ instead.'
}

if (Test-Path -LiteralPath $OutDir) {
    $old = @(Get-ChildItem -LiteralPath $OutDir -Filter '*.lnk' -File -ErrorAction SilentlyContinue)
    if ($old.Count -gt 0 -and -not $Force) {
        throw "Folder already holds $($old.Count) shortcuts: $OutDir`n" +
              "Default is NOT to overwrite it (desktop 'my_portal' controls the production instance).`n" +
              "Pass -Force to replace, or choose another -FolderName."
    }
} else {
    New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
}

$links = @(
    @{ n = '0-status';          b = '0-status.bat';                       d = 'Check ports and entry URLs (read only)' },
    @{ n = '1-start-all';       b = '1-start-all.bat';                    d = 'Start all four subsystems' },
    @{ n = '2-stop-all';        b = '2-stop-all.bat';                     d = 'Stop only services this copy started' },
    @{ n = '3-start-dryrun';    b = '3-start-dryrun.bat';                 d = 'Preview the start plan, start nothing' },
    @{ n = '4-stop-dryrun';     b = '4-stop-dryrun.bat';                  d = 'Preview the stop plan' },
    @{ n = '5-nginx-check';     b = '5-nginx-check.bat';                  d = 'Regenerate nginx.conf from .env and validate' },
    @{ n = '6-open-home';       b = '6-open-home.bat';                    d = 'Open https://localhost/ navigation page' },
    @{ n = '7-open-logs';       b = '7-open-logs.bat';                    d = 'Open TMP log folder' },
    @{ n = '8-install-links';   b = '8-install-desktop-shortcuts.bat';    d = 'Re-create these desktop shortcuts' }
)

$shell = New-Object -ComObject WScript.Shell
$icon = "$env:SystemRoot\System32\shell32.dll,137"
$made = @()
foreach ($l in $links) {
    $bat = Join-Path $PSScriptRoot $l.b
    if (-not (Test-Path -LiteralPath $bat)) { Write-Warning "Missing entry, skipped: $($l.b)"; continue }
    $lnkPath = Join-Path $OutDir ($l.n + '.lnk')
    $lnk = $shell.CreateShortcut($lnkPath)
    $lnk.TargetPath = $bat
    $lnk.Arguments = ''
    $lnk.WorkingDirectory = $Root
    $lnk.Description = $l.d
    $lnk.IconLocation = $icon
    $lnk.WindowStyle = 1
    $lnk.Save()
    if (Test-Path -LiteralPath $lnkPath) { $made += $l.n }
}

Write-Host ''
Write-Host "Created $($made.Count) shortcuts in: $OutDir" -ForegroundColor Green
Write-Host "Pointing at copy root: $Root"
foreach ($m in $made) { Write-Host "  $m.lnk" }
Write-Host ''
Write-Host 'These shortcuts control ONLY this portable copy. The desktop' -ForegroundColor Yellow
Write-Host "'my_portal' folder (production instance) is untouched." -ForegroundColor Yellow
