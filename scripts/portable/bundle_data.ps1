<#
  bundle_data.ps1 —— 把生产 PostgreSQL 快照灌进离线副本的便携实例
  =============================================================================
  为什么单独一个脚本：build_olbr_portable.ps1 的 data 阶段刻意不做数据搬运。
  打包源码可以随便重跑，导出/灌库是重操作且**会读到生产明文口令**，
  必须单独跑、可单独 -DryRun，且在任何日志里都不打印连接串。

  两个阶段（可分开跑）：
    dump     从主仓库 backend\.env 的 DATABASE_URL 读生产连接信息，pg_dump -Fc 落盘
    restore  副本 runtime\pgdata 首次 initdb -> pg_ctl start -> createdb -> pg_restore
    all      两者都做（默认）

  ⚠ 本文件**不含任何真实口令/Token**：口令在运行时从 SourceEnv 读进内存，
    只通过进程环境变量 PGPASSWORD 传给 pg_dump，用完立即清除；连接串不进日志、
    不落盘、不写进副本的 .env（副本用 trust 认证的回环连接，见 env_template.txt）。

  用法（在**能连到生产库的机器**上跑）：
    powershell -NoProfile -File scripts\portable\bundle_data.ps1 -DryRun
    powershell -NoProfile -File scripts\portable\bundle_data.ps1 -Stage all
    powershell -NoProfile -File scripts\portable\bundle_data.ps1 -Stage restore
  =============================================================================
#>
[CmdletBinding()]
param(
    [string]$MainRepo = 'D:\01_RPA',
    [string]$CopyRoot = 'D:\01_olbr_portal',
    [string]$SourceEnv = '',
    [string]$PgBin = 'C:\Program Files\PostgreSQL\16\bin',
    [ValidateSet('all', 'dump', 'restore')]
    [string]$Stage = 'all',
    [string]$DumpFile = '',
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
if (-not $SourceEnv) { $SourceEnv = Join-Path $MainRepo 'Task\my_app\backend\.env' }
if (-not $DumpFile) { $DumpFile = Join-Path $CopyRoot 'TMP\myapp_snapshot.dump' }
$sw = [System.Diagnostics.Stopwatch]::StartNew()

function Write-Step { param([string]$m) Write-Host "[*] $m" }
function Write-Ok { param([string]$m) Write-Host "[OK] $m" -ForegroundColor Green }
function Write-Warn2 { param([string]$m) Write-Host "[WARN] $m" -ForegroundColor Yellow }

# 从副本 .env 读目标端口/库名（不复制口令，副本侧只有 trust 认证）
function Get-CopyCfg {
    param([string]$Key, [string]$Default)
    $f = Join-Path $CopyRoot '.env'
    if (-not (Test-Path -LiteralPath $f)) { return $Default }
    foreach ($line in [System.IO.File]::ReadAllLines($f, [System.Text.Encoding]::UTF8)) {
        $t = $line.Trim()
        if ($t -match ('^' + [regex]::Escape($Key) + '=(.*)$') -and $Matches[1]) { return $Matches[1].Trim() }
    }
    return $Default
}
$TgtPort = [int](Get-CopyCfg 'PGPORT' '55432')
$TgtUser = Get-CopyCfg 'MY_APP_DB_USER' 'myapp'
$TgtDb = Get-CopyCfg 'MY_APP_DB_NAME' 'myapp'
if ($TgtUser -notmatch '^[A-Za-z0-9_]+$' -or $TgtDb -notmatch '^[A-Za-z0-9_]+$') {
    throw '副本 .env 的 MY_APP_DB_USER / MY_APP_DB_NAME 只允许字母数字下划线'
}

function Invoke-Dump {
    Write-Step '=== 阶段 dump：从生产 PG 导出 ==='
    if (-not (Test-Path -LiteralPath $SourceEnv)) { throw "找不到生产 .env：$SourceEnv" }
    $url = ''
    foreach ($line in [System.IO.File]::ReadAllLines($SourceEnv, [System.Text.Encoding]::UTF8)) {
        $t = $line.Trim()
        if ($t.StartsWith('DATABASE_URL=')) { $url = $t.Substring('DATABASE_URL='.Length).Trim().Trim('"').Trim("'"); break }
    }
    if (-not $url) { throw "SourceEnv 里没有 DATABASE_URL：$SourceEnv" }
    # 只解析，不打印：$url 含明文口令，任何 Write-Host 都不得带上它（含异常消息）
    $m = [regex]::Match($url, '^postgresql(?:\+\w+)?://(?<u>[^:/@]+)(?::(?<p>[^@]*))?@(?<h>[^:/]+)(?::(?<port>\d+))?/(?<db>[^?]+)')
    if (-not $m.Success) { throw 'DATABASE_URL 格式无法解析（期望 postgresql://user:pass@host:port/db）' }
    $srcUser = $m.Groups['u'].Value
    $srcPass = [System.Uri]::UnescapeDataString($m.Groups['p'].Value)
    $srcHost = $m.Groups['h'].Value
    $srcPort = if ($m.Groups['port'].Value) { [int]$m.Groups['port'].Value } else { 5432 }
    $srcDb = $m.Groups['db'].Value
    $pgDump = Join-Path $PgBin 'pg_dump.exe'
    if (-not (Test-Path -LiteralPath $pgDump)) { throw "缺 pg_dump.exe：$pgDump（用 -PgBin 指定 PostgreSQL 16 的 bin）" }
    $dumpDir = Split-Path -Parent $DumpFile
    if (-not (Test-Path -LiteralPath $dumpDir)) { New-Item -ItemType Directory -Path $dumpDir -Force | Out-Null }

    Write-Step ("源库：{0}:{1}/{2}（连接串含口令，不打印）" -f $srcHost, $srcPort, $srcDb)
    if ($DryRun) { Write-Step "<干跑> pg_dump -Fc -> $DumpFile"; return }
    try {
        # PGPASSWORD 只在本进程生存期内有效，子进程继承后即可连接；绝不写进磁盘
        $env:PGPASSWORD = $srcPass
        & $pgDump -Fc -h $srcHost -p $srcPort -U $srcUser -d $srcDb -f $DumpFile 2>&1 |
            ForEach-Object { Write-Host "  $_" }
        if ($LASTEXITCODE -ne 0) { throw "pg_dump 失败（exit=$LASTEXITCODE）" }
    } finally {
        Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue
        [void]$srcPass
    }
    $size = (Get-Item -LiteralPath $DumpFile).Length / 1MB
    Write-Ok ("快照已导出：{0}（{1:N1} MB）" -f $DumpFile, $size)
}

function Invoke-Restore {
    Write-Step '=== 阶段 restore：灌入副本便携 PG ==='
    if (-not (Test-Path -LiteralPath $DumpFile)) { throw "找不到快照：$DumpFile（先跑 -Stage dump）" }
    if (-not (Test-Path -LiteralPath $CopyRoot)) { throw "副本根目录不存在：$CopyRoot" }
    $bin = Join-Path $CopyRoot 'runtime\postgresql16\bin'
    $pgData = Join-Path $CopyRoot 'runtime\pgdata'
    $initdb = Join-Path $bin 'initdb.exe'
    $pgCtl = Join-Path $bin 'pg_ctl.exe'
    $psql = Join-Path $bin 'psql.exe'
    $createdb = Join-Path $bin 'createdb.exe'
    $pgRestore = Join-Path $bin 'pg_restore.exe'
    foreach ($exe in @($initdb, $pgCtl, $psql, $createdb, $pgRestore)) {
        if (-not (Test-Path -LiteralPath $exe)) { throw "副本缺 PG 工具：$exe（请先跑 -Stage runtimes）" }
    }

    if (-not (Test-Path -LiteralPath (Join-Path $pgData 'PG_VERSION'))) {
        Write-Step "首次恢复，initdb -> $pgData"
        if ($DryRun) { Write-Step '<干跑> 跳过 initdb' }
        else {
            & $initdb -D $pgData -U $TgtUser -A trust --encoding=UTF8 2>&1 | ForEach-Object { Write-Host "  $_" }
            if ($LASTEXITCODE -ne 0) { throw "initdb 失败（exit=$LASTEXITCODE）" }
        }
    }
    $pgLog = Join-Path $CopyRoot 'TMP\portable-pg.log'
    if ($DryRun) {
        Write-Step ('<干跑> pg_ctl start / createdb / pg_restore（目标 127.0.0.1:{0}/{1}）' -f $TgtPort, $TgtDb)
        return
    }
    & $pgCtl -D $pgData status 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        & $pgCtl -D $pgData -l $pgLog -o "-p $TgtPort -h 127.0.0.1" start 2>&1 | ForEach-Object { Write-Host "  $_" }
        if ($LASTEXITCODE -ne 0) { throw "pg_ctl start 失败，见 $pgLog" }
    }
    $exists = & $psql -h 127.0.0.1 -p $TgtPort -U $TgtUser -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$TgtDb'" 2>$null
    if (-not $exists) {
        & $createdb -h 127.0.0.1 -p $TgtPort -U $TgtUser $TgtDb 2>&1 | ForEach-Object { Write-Host "  $_" }
    }
    # --no-owner / --no-privileges：生产侧的 role 在副本不存在，否则恢复会一路报错
    & $pgRestore --clean --if-exists --no-owner --no-privileges `
        -h 127.0.0.1 -p $TgtPort -U $TgtUser -d $TgtDb $DumpFile 2>&1 |
        ForEach-Object { Write-Host "  $_" }
    if ($LASTEXITCODE -ne 0) {
        Write-Warn2 "pg_restore 返回 exit=$LASTEXITCODE（--clean 下对象不存在会产生无害报错，请核对下方行数）"
    }
    $tables = & $psql -h 127.0.0.1 -p $TgtPort -U $TgtUser -d $TgtDb -tAc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'" 2>$null
    Write-Ok ("恢复完成：public schema 共 {0} 张表" -f ($tables.Trim()))
}

if ($Stage -in @('all', 'dump')) { Invoke-Dump }
if ($Stage -in @('all', 'restore')) { Invoke-Restore }
$sw.Stop()
Write-Ok ("bundle_data 完成（{0}），耗时 {1:N1} 秒{2}" -f $Stage, $sw.Elapsed.TotalSeconds, $(if ($DryRun) { '（干跑）' } else { '' }))
