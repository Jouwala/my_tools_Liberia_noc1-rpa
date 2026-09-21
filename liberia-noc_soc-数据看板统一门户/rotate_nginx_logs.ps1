# rotate_nginx_logs.ps1 - bound the size of THIS host's nginx access log.
#
# Why: nginx.conf now writes the access log as logs/access-$hostname.log inside the
# nginx install prefix. For this host that prefix is the share Y:\01_RPA\nginx-1.28.0
# (E: on .19), and nginx never rotates logs by itself - the old shared access.log had
# grown to 826 MB before 2026-09-21 with no rotation at all.
#
# How it rotates without touching nginx (nginx holds the file open, so a plain
# Move-Item would fail with a sharing violation):
#   1. copy the live log to access-<host>-<stamp>.log
#   2. truncate the original in place through a FileStream opened with a ReadWrite
#      share. nginx opens log files with FILE_APPEND_DATA, so its next buffered
#      flush lands at the new end of file: no reload, no restart, no lost lines.
#   3. zip the copy, delete the plain copy, prune zips older than KeepDays.
#
# Scope: only this host's own access log. error.log is still shared with .19's nginx
# (nginx does not allow variables in an error_log path) and the legacy access.log is
# still being written by .19 until that host reloads - neither is touched here.
#
# Sizing note (measured 2026-09-21): this host writes roughly 400 KB per 5 minutes
# (~120 MB/day) because the my_app dashboards poll /api/tasks from every client, so
# the task runs every 6 hours with a 20 MB threshold rather than once a day.
#
# ASCII only on purpose: Windows PowerShell 5.1 reads a BOM-less .ps1 as ANSI, so
# non-ASCII text in this file can be garbled and break parsing. Same rule as
# start_hidden.ps1.
#
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File rotate_nginx_logs.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File rotate_nginx_logs.ps1 -DryRun
param(
    [string]$Prefix = 'Y:\01_RPA\nginx-1.28.0\',
    [int]$MinSizeMB = 20,
    [int]$KeepDays = 14,
    [switch]$DryRun
)

$ErrorActionPreference = 'Continue'
$logDir = Join-Path $Prefix 'logs'
$name = 'access-' + $env:COMPUTERNAME
$current = Join-Path $logDir ($name + '.log')

if (-not (Test-Path $current)) {
    Write-Output "[skip] no access log yet: $current"
    exit 0
}

$size = (Get-Item $current).Length
$sizeMB = [math]::Round($size / 1MB, 2)
if ($size -lt ($MinSizeMB * 1MB)) {
    Write-Output "[skip] $current is $sizeMB MB (below the $MinSizeMB MB threshold)"
    exit 0
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$archive = Join-Path $logDir ($name + '-' + $stamp + '.log')
$zip = $archive + '.zip'

if ($DryRun) {
    Write-Output "[dry-run] would rotate $current ($sizeMB MB) -> $zip"
    exit 0
}

try {
    Copy-Item -Path $current -Destination $archive -Force -ErrorAction Stop
} catch {
    Write-Output "[FAIL] copy failed, log left untouched: $($_.Exception.Message)"
    exit 1
}

try {
    # Truncate in place while nginx keeps its handle open (share mode must let its
    # writer through, otherwise this throws a sharing violation).
    $fs = [System.IO.File]::Open($current,
        [System.IO.FileMode]::Truncate,
        [System.IO.FileAccess]::Write,
        [System.IO.FileShare]::ReadWrite)
    $fs.Flush()
    $fs.Close()
} catch {
    Write-Output "[FAIL] truncate failed, archive kept at $archive : $($_.Exception.Message)"
    exit 1
}

Compress-Archive -Path $archive -DestinationPath $zip -Force -ErrorAction SilentlyContinue
if (Test-Path $zip) {
    Remove-Item $archive -Force -ErrorAction SilentlyContinue
} else {
    Write-Output "[warn] zip failed, keeping plain archive $archive"
}

$cutoff = (Get-Date).AddDays(-$KeepDays)
$old = @(Get-ChildItem -Path $logDir -Filter ($name + '-*.log.zip') -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt $cutoff })
foreach ($f in $old) { Remove-Item $f.FullName -Force -ErrorAction SilentlyContinue }

Write-Output "[ok] rotated $sizeMB MB -> $zip ; pruned $($old.Count) archive(s) older than $KeepDays day(s)"
exit 0
