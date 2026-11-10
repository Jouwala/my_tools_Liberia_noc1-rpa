# post_sync_fix_paths.ps1 -- re-apply copy-local path fixes after a source sync.
#
# Single source of truth: D:\01_RPA\scripts\portable\post_sync_fix_paths.ps1
# The copy receives it via the `config` stage of build_olbr_portable.ps1.
# Do not edit D:\01_olbr_portal\scripts\post_sync_fix_paths.ps1 by hand --
# it is overwritten on every config stage. Edit the one in the main repo.
#
# Why: `build_olbr_portable.ps1 -Stage source` copies Task/my_app and the portal
# subtree verbatim from D:\01_RPA, so two scripts that were hand-fixed for the
# isolated copy get reverted to D:\01_RPA paths on every sync:
#
#   1) Task\my_app\monitor_fixes\nginx_monitor.ps1   (NginxExe/NginxDir/Port/Log/State)
#   2) <portal>\rotate_nginx_logs.ps1                ($Prefix)
#
# Reverting them is not fatal while the copy is idle, but at cutover the nginx
# watchdog would probe D:\01_RPA\nginx-1.28.0\nginx.exe (port 80) instead of the
# copy's own instance, and could spawn a second nginx that fights for the port.
#
# ---------------------------------------------------------------------------------------
# Byte-level fidelity (this matters because the copy is a git repo)
# ---------------------------------------------------------------------------------------
# The two target files are TRACKED in D:\01_olbr_portal. If this script rewrote them
# with different encoding, every sync would leave `git status` dirty forever and the
# committed version could never be reproduced.
#
#   * rotate_nginx_logs.ps1 is **no-BOM + LF** in the main repo
#   * nginx_monitor.ps1    is **BOM + CRLF** in the main repo
#
# So the rewrite below preserves, byte for byte:
#   - the UTF-8 BOM flag (present or absent) of each file
#   - the line ending style (LF vs CRLF) of each file
#   - every byte it does not deliberately replace
#
# It never uses Set-Content / Get-Content for the payload (PS 5.1 would add a BOM
# and normalise line endings), it goes through raw bytes instead.
#
# ---------------------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------------------
# Refuses to touch anything unless the target really is the isolated copy
# (ISOLATED_COPY.flag present). The main repo has no such flag, so running this
# against D:\01_RPA by mistake is a no-op -- it can never rewrite production paths.
# Pass -Force to override (needed right after `git clone`, where the flag is not
# tracked by git and therefore missing).
#
# Idempotent: safe to run any number of times.
#
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\post_sync_fix_paths.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\post_sync_fix_paths.ps1 -Force
#
# ASCII-only body on purpose: PS 5.1 reads a .ps1 without a BOM as ANSI, and this
# script runs on machines where the code page is not UTF-8. No Chinese literals.
# ---------------------------------------------------------------------------------------

[CmdletBinding()]
param(
    [string]$CopyRoot = '',
    [switch]$Force,
    [switch]$Quiet
)

$ErrorActionPreference = 'Stop'

function Write-Msg {
    param([string]$Text, [string]$Color = 'Gray')
    if ($Quiet) { return }
    Write-Host $Text -ForegroundColor $Color
}

# $PSScriptRoot can be empty during param binding in some hosts; resolve here.
if (-not $CopyRoot) {
    $here = Split-Path -Parent $MyInvocation.MyCommand.Path
    $CopyRoot = Split-Path -Parent $here
}

if (-not (Test-Path -LiteralPath $CopyRoot)) {
    throw "Copy root does not exist: $CopyRoot"
}

# Normalize to a canonical absolute path with plain backslashes.
# The rewritten values end up inside committed files, so they must be byte-stable:
# a root handed in as 'D:/01_olbr_portal' would otherwise produce
# "D:/01_olbr_portal\nginx-1.28.0" (mixed separators) in the tracked scripts,
# and the committed version could never be reproduced.
$CopyRoot = (Resolve-Path -LiteralPath $CopyRoot).Path.TrimEnd('\')

$flag = Join-Path $CopyRoot 'ISOLATED_COPY.flag'
if (-not (Test-Path -LiteralPath $flag)) {
    if (-not $Force) {
        Write-Msg "[SKIP] $CopyRoot is not an isolated copy (no ISOLATED_COPY.flag)." 'Yellow'
        Write-Msg '       Pass -Force to apply the path fixes anyway (e.g. right after git clone).' 'DarkGray'
        exit 0
    }
    Write-Msg '[WARN] ISOLATED_COPY.flag missing -- running with -Force.' 'Yellow'
}

# --------------------------------------------------------------- byte-safe rewrite
function Get-TextPreserving {
    # Reads a file as UTF-8 text and reports whether it carried a BOM.
    param([string]$Path)
    $bytes = [System.IO.File]::ReadAllBytes($Path)
    $hasBom = ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF)
    $text = [System.Text.Encoding]::UTF8.GetString($bytes)
    if ($hasBom) { $text = $text.Substring(1) }
    return @{ Text = $text; HasBom = $hasBom }
}

function Set-TextPreserving {
    # Writes UTF-8 text back, restoring the original BOM flag.
    # Line endings inside $Text are written verbatim, so LF stays LF and CRLF stays CRLF.
    param([string]$Path, [string]$Text, [bool]$HasBom)
    $out = [System.Text.Encoding]::UTF8.GetBytes($Text)
    if ($HasBom) {
        $withBom = New-Object byte[] ($out.Length + 3)
        $withBom[0] = 0xEF; $withBom[1] = 0xBB; $withBom[2] = 0xBF
        [System.Array]::Copy($out, 0, $withBom, 3, $out.Length)
        $out = $withBom
    }
    [System.IO.File]::WriteAllBytes($Path, $out)
}

function Read-EnvPort {
    param([string]$Key, [int]$Default)
    $envFile = Join-Path $CopyRoot '.env'
    if (-not (Test-Path -LiteralPath $envFile)) { return $Default }
    foreach ($line in Get-Content -LiteralPath $envFile) {
        if ($line -match ('^\s*' + [regex]::Escape($Key) + '\s*=\s*(\d+)')) { return [int]$Matches[1] }
    }
    return $Default
}

# --------------------------------------------------------------------- replacement
# Why a MatchEvaluator instead of a replacement string:
#   [regex]::Replace's replacement argument treats both '$' and '\' as special.
#   A Windows path contains '\' (which '\n' would turn into a newline) and may
#   contain '$' (which '$1' would turn into a group reference). Building the
#   result through a callback avoids the whole escaping minefield: the callback
#   returns the literal text, verbatim.
function Set-ParamDefault {
    # Rewrites the default value of a single parameter inside a param() block.
    # Matches:  [<type>]$<name> = <quoted value>      (string paths)
    #           [<type>]$<name> = <bare number>        (int ports)
    param(
        [string]$Text,
        [string]$ParamType,
        [string]$ParamName,
        [string]$NewValue,
        [string]$Quote = '"'
    )
    $head = '(\[\s*' + [regex]::Escape($ParamType) + '\s*\]\s*\$' + [regex]::Escape($ParamName) + '\s*=\s*)'
    # q = snapshot for the callback (see GetNewClosure below)
    $q = $Quote
    $v = $NewValue

    if ($Quote -eq '') {
        # Bare numeric value, e.g. [int]$NginxPort = 80
        $pattern = $head + '-?\d+'
        $evaluator = [System.Text.RegularExpressions.MatchEvaluator] {
            param($m)
            $m.Groups[1].Value + $v
        }.GetNewClosure()
    } else {
        $pattern = $head + [regex]::Escape($Quote) + '[^' + [regex]::Escape($Quote) + ']*' + [regex]::Escape($Quote)
        $evaluator = [System.Text.RegularExpressions.MatchEvaluator] {
            param($m)
            $m.Groups[1].Value + $q + $v + $q
        }.GetNewClosure()
    }
    return [regex]::Replace($Text, $pattern, $evaluator)
}

$httpPort = Read-EnvPort -Key 'NGINX_HTTP_PORT' -Default 8080
$nginxDir = Join-Path $CopyRoot 'nginx-1.28.0'
$nginxExe = Join-Path $nginxDir 'nginx.exe'
$logPath = Join-Path $CopyRoot 'Task\nginx_monitor.log'
$statePath = Join-Path $CopyRoot 'Task\nginx_monitor.state'
$changed = 0

# ---------------------------------------------------------------- 1) nginx_monitor
$mon = Join-Path $CopyRoot 'Task\my_app\monitor_fixes\nginx_monitor.ps1'
if (Test-Path -LiteralPath $mon) {
    $state = Get-TextPreserving -Path $mon
    $text = $state.Text
    $orig = $text
    # Only rewrite the default values inside the param() block.
    $text = Set-ParamDefault -Text $text -ParamType 'string' -ParamName 'NginxExe' -NewValue $nginxExe
    $text = Set-ParamDefault -Text $text -ParamType 'string' -ParamName 'NginxDir' -NewValue $nginxDir
    $text = Set-ParamDefault -Text $text -ParamType 'int'    -ParamName 'NginxPort' -NewValue ([string]$httpPort) -Quote ''
    $text = Set-ParamDefault -Text $text -ParamType 'string' -ParamName 'LogPath' -NewValue $logPath
    $text = Set-ParamDefault -Text $text -ParamType 'string' -ParamName 'StatePath' -NewValue $statePath
    if ($text -ne $orig) {
        Set-TextPreserving -Path $mon -Text $text -HasBom $state.HasBom
        Write-Msg "[FIX] nginx_monitor.ps1 -> copy paths, port $httpPort" 'Green'
        $changed++
    } else {
        Write-Msg '[OK ] nginx_monitor.ps1 already points to the copy' 'DarkGray'
    }
} else {
    Write-Msg "[MISS] $mon" 'DarkYellow'
}

# ------------------------------------------------------------ 2) rotate_nginx_logs
# The portal folder name is Chinese, so locate it by probing for the script
# instead of hardcoding a literal (PS 5.1 reads .ps1 as ANSI without a BOM).
$rot = $null
foreach ($d in (Get-ChildItem -LiteralPath $CopyRoot -Directory -ErrorAction SilentlyContinue)) {
    $cand = Join-Path $d.FullName 'rotate_nginx_logs.ps1'
    if (Test-Path -LiteralPath $cand) { $rot = $cand; break }
}
if ($rot) {
    $state = Get-TextPreserving -Path $rot
    $text = $state.Text
    $orig = $text
    $text = Set-ParamDefault -Text $text -ParamType 'string' -ParamName 'Prefix' -NewValue ($nginxDir + '\') -Quote "'"
    if ($text -ne $orig) {
        Set-TextPreserving -Path $rot -Text $text -HasBom $state.HasBom
        Write-Msg "[FIX] rotate_nginx_logs.ps1 `$Prefix -> $nginxDir" 'Green'
        $changed++
    } else {
        Write-Msg '[OK ] rotate_nginx_logs.ps1 already points to the copy' 'DarkGray'
    }
} else {
    Write-Msg '[MISS] rotate_nginx_logs.ps1 not found under the copy root' 'DarkYellow'
}

Write-Msg ("Done. {0} file(s) changed." -f $changed) 'Cyan'
exit 0
