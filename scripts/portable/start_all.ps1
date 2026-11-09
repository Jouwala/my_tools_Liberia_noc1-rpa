<#
  start_all.ps1 —— 离线副本一键启动（由 build_olbr_portable.ps1 -Stage config 铺到 <副本根>\scripts\）
  =============================================================================
  入口：副本根目录的 start.bat（薄壳，只调本脚本）。
  真相源：副本根 .env（模板 scripts\env_template.txt）；端口与盘符都不写死。

  与生产启动脚本的区别（重要，别照抄 my_portal_ctl.ps1）：
    · 生产用 start_hidden.ps1 拉 backend_watchdog + worker 组 + 开机自启任务；
      副本**全部不用** —— MY_APP_DISABLE_SCHEDULER=1 且不设 MY_APP_TASK_QUEUE，
      否则采集任务会连生产上游、并可能重复投递 WhatsApp/邮件告警。
    · 副本直接起 uvicorn / vite preview / tsx server，进程由本脚本用 pid 文件托管；
      stop_all.ps1 只按 pid 文件停，绝不按端口盲杀（源机可能正在跑生产）。
    · 解释器一律用副本自带的 runtime\python312 / runtime\node，路径由 $Root 推出。

  PowerShell 5.1 兼容：不用 ::new()、三元、-Parallel、$IsWindows。
  用法：
    powershell -NoProfile -File scripts\start_all.ps1
    powershell -NoProfile -File scripts\start_all.ps1 -DryRun
  =============================================================================
#>
[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$SkipNginxConf
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$sw = [System.Diagnostics.Stopwatch]::StartNew()

# 本脚本位于 <Root>\scripts\，故根 = 上一级
$Root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$TmpDir = Join-Path $Root 'TMP'
$RuntimeDir = Join-Path $Root 'runtime'
$PyExe = Join-Path $RuntimeDir 'python312\python.exe'
$NodeExe = Join-Path $RuntimeDir 'node\node.exe'
$PgBin = Join-Path $RuntimeDir 'postgresql16\bin'
$NginxDir = Join-Path $Root 'nginx-1.28.0'
$NginxExe = Join-Path $NginxDir 'nginx.exe'
$MyAppDir = Join-Path $Root 'Task\my_app'
$FeDir = Join-Path $MyAppDir 'frontend'
$BotDir = Join-Path $Root 'Task\whatsapp-kb-bot'
$PortalDir = Get-ChildItem -LiteralPath $Root -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like 'liberia-noc_soc-*' } | Select-Object -First 1
$PortalRoot = if ($PortalDir) { $PortalDir.FullName } else { $null }

# 防误跑：本脚本只应在 build 出来的副本里执行。主仓库同样有 Task\my_app，
# 但没有 runtime\node\node.exe —— 少了这道检查，误在主仓库跑会往源码树写 .env。
if (-not (Test-Path -LiteralPath $NodeExe) -or
    -not (Test-Path -LiteralPath (Join-Path $MyAppDir 'backend\main.py'))) {
    throw "当前目录不是有效副本（缺 runtime\node\node.exe 或 Task\my_app\backend\main.py）：$Root`n本脚本只能在 build_olbr_portable.ps1 生成的副本里运行。"
}

function Write-Step { param([string]$m) Write-Host "[*] $m" }
function Write-Ok { param([string]$m) Write-Host "[OK] $m" -ForegroundColor Green }
function Write-Warn2 { param([string]$m) Write-Host "[WARN] $m" -ForegroundColor Yellow }
function Write-Err2 { param([string]$m) Write-Host "[FAIL] $m" -ForegroundColor Red }
function Write-Skip { param([string]$m) Write-Host "[SKIP] $m" -ForegroundColor DarkGray }

if (-not $DryRun -and -not (Test-Path -LiteralPath $TmpDir)) {
    New-Item -ItemType Directory -Path $TmpDir -Force | Out-Null
}

# ---------------------------------------------------------------- .env 载入
# 规则与 env_template.txt 的注释一致：已在进程/系统里存在的同名变量优先，
# 所以可临时用 $env:XXX 覆盖而不改文件；模板里的空值表示「由本脚本派生」。
function Import-DotEnv {
    param([string]$Path)
    $cfg = @{}
    if (-not (Test-Path -LiteralPath $Path)) { return $cfg }
    foreach ($line in [System.IO.File]::ReadAllLines($Path, [System.Text.Encoding]::UTF8)) {
        $t = $line.Trim()
        if (-not $t -or $t.StartsWith('#')) { continue }
        $i = $t.IndexOf('=')
        if ($i -le 0) { continue }
        $k = $t.Substring(0, $i).Trim()
        $v = $t.Substring($i + 1).Trim()
        $cfg[$k] = $v
    }
    return $cfg
}

$envFile = Join-Path $Root '.env'
$envTpl = Join-Path $PSScriptRoot 'env_template.txt'
if (-not (Test-Path -LiteralPath $envFile)) {
    if (-not (Test-Path -LiteralPath $envTpl)) { throw "缺少 .env 模板: $envTpl" }
    if (-not $DryRun) { Copy-Item -LiteralPath $envTpl -Destination $envFile -Force }
    Write-Step "首次启动：已从模板生成 $envFile"
}
$cfg = Import-DotEnv $envFile

function Get-Cfg {
    param([string]$Key, [string]$Default = '')
    $existing = [Environment]::GetEnvironmentVariable($Key, 'Process')
    if ($existing) { return $existing }
    if ($cfg.ContainsKey($Key) -and $cfg[$Key]) { return $cfg[$Key] }
    return $Default
}
function Set-Cfg {
    param([string]$Key, [string]$Value)
    [Environment]::SetEnvironmentVariable($Key, $Value, 'Process')
}

$HttpPort = [int](Get-Cfg 'NGINX_HTTP_PORT' '80')
$BePort = [int](Get-Cfg 'MY_APP_BE_PORT' '7038')
$FePort = [int](Get-Cfg 'MY_APP_FE_PORT' '7090')
$PortalPort = [int](Get-Cfg 'PORTAL_PORT' '9267')
$PgPort = [int](Get-Cfg 'PGPORT' '55432')
$QaPort = [int](Get-Cfg 'QA_HTTP_PORT' '9269')
$WaAnalysisPort = [int](Get-Cfg 'WA_ANALYSIS_PORT' '9268')
$PgUser = Get-Cfg 'MY_APP_DB_USER' 'myapp'
$PgDb = Get-Cfg 'MY_APP_DB_NAME' 'myapp'
if ($PgUser -notmatch '^[A-Za-z0-9_]+$' -or $PgDb -notmatch '^[A-Za-z0-9_]+$') {
    throw 'MY_APP_DB_USER / MY_APP_DB_NAME 只允许字母数字下划线（会被拼进 psql 命令）'
}

# ------------------------------------------------------- 派生变量（盘符无关）
$PgData = Join-Path $RuntimeDir 'pgdata'
$FeDist = (Join-Path $Root 'Task\_fe_dist').Replace('\', '/')
$AuthDir = Join-Path $RuntimeDir 'portal-auth-data'
if (-not $DryRun -and -not (Test-Path -LiteralPath $AuthDir)) {
    New-Item -ItemType Directory -Path $AuthDir -Force | Out-Null
}

# 便携 PG 用 trust 认证且只绑回环，连接串里刻意没有口令 —— 绝不把生产 .env 的
# 明文口令带进副本。database.py 的 load_dotenv(override=False) 保证进程环境优先。
$dbUrl = 'postgresql://{0}@127.0.0.1:{1}/{2}' -f $PgUser, $PgPort, $PgDb
$derived = [ordered]@{
    'PGDATA' = $PgData
    'FE_DIST_OUT' = $FeDist
    'PORTAL_AUTH_DATA_DIR' = $AuthDir
    'PORTAL_QA_NODE' = $NodeExe
    'PORTAL_QA_PORT' = [string]$QaPort
    'PORTAL_QA_HOST' = '127.0.0.1'
    'QA_HTTP_HOST' = '127.0.0.1'
    'QA_HTTP_PORT' = [string]$QaPort
    'MY_APP_API_BASE' = 'http://127.0.0.1:{0}' -f $BePort
    'MY_APP_BACKEND_PORT' = [string]$BePort
    'MY_APP_DB_MODE' = 'pg'
    'DATABASE_URL' = $dbUrl
    'PORT' = [string]$PortalPort
    'PORTAL_HOST' = '127.0.0.1'
    'PGHOSTADDR' = '127.0.0.1'
}
foreach ($k in $derived.Keys) {
    if (-not [Environment]::GetEnvironmentVariable($k, 'Process')) { Set-Cfg $k $derived[$k] }
}

# 安全熔断：副本必须禁用调度器，不允许被 .env 改回 0
if ((Get-Cfg 'MY_APP_DISABLE_SCHEDULER' '1') -ne '1') {
    Write-Warn2 '.env 里 MY_APP_DISABLE_SCHEDULER != 1，已强制改回 1（副本禁止连生产采集上游）'
}
Set-Cfg 'MY_APP_DISABLE_SCHEDULER' '1'
Remove-Item Env:\MY_APP_TASK_QUEUE -ErrorAction SilentlyContinue

# 让子进程用副本自带解释器（其余 PATH 保留，避免影响 psql 之类外部命令）
$env:PATH = '{0};{1};{2}' -f (Split-Path $NodeExe -Parent), (Split-Path $PyExe -Parent), $env:PATH

# backend\.env 只写本地 trust 连接串，不含任何真实口令；已存在则不覆盖（使用者可能自己改过）
$backendEnv = Join-Path $MyAppDir 'backend\.env'
if (-not (Test-Path -LiteralPath $backendEnv)) {
    if (-not $DryRun) {
        $utf8NoBom = New-Object System.Text.UTF8Encoding $false
        $body = "MY_APP_DB_MODE=pg`r`nDATABASE_URL=$dbUrl`r`nMY_APP_DISABLE_SCHEDULER=1`r`n"
        [System.IO.File]::WriteAllText($backendEnv, $body, $utf8NoBom)
    }
    if ($DryRun) { Write-Step "<干跑> 将生成 $backendEnv（仅本地回环连接，无口令）" }
    else { Write-Step "已生成 $backendEnv（仅本地回环连接，无口令）" }
}

# ------------------------------------------------------------------ 通用工具
function Test-PortListening {
    param([int]$Port, [int]$TimeoutMs = 1200)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect('127.0.0.1', $Port, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne($TimeoutMs, $false)) { return $false }
        $client.EndConnect($async)
        return $true
    } catch { return $false }
    finally { try { $client.Close(); $client.Dispose() } catch { } }
}
function Wait-Port {
    param([int]$Port, [int]$Seconds = 30)
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-PortListening $Port) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return (Test-PortListening $Port)
}
function Quote-Arg {
    param([string]$a)
    if ($a -match '\s' -and -not $a.StartsWith('"')) { return '"' + $a + '"' }
    return $a
}
function Get-PidFile { param([string]$Name) Join-Path $TmpDir ("portable-$Name.pid") }
function Save-Pid {
    param([string]$Name, [int]$ProcessId)
    $p = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if (-not $p) { return }
    $ticks = $p.StartTime.Ticks
    [System.IO.File]::WriteAllText((Get-PidFile $Name), "$ProcessId|$($p.ProcessName)|$ticks")
}

# 按 pid 文件判定「本副本上一轮是否已起过」，避免重复启动，也避免抢别人的端口
function Test-OwnPort {
    param([string]$Name, [int]$Port)
    if (-not (Test-PortListening $Port)) { return $false }
    $pf = Get-PidFile $Name
    if (Test-Path -LiteralPath $pf) {
        $parts = ([System.IO.File]::ReadAllText($pf)).Trim() -split '\|'
        if ($parts.Count -eq 3) {
            $p = Get-Process -Id ([int]$parts[0]) -ErrorAction SilentlyContinue
            if ($p -and $p.ProcessName -eq $parts[1] -and $p.StartTime.Ticks -eq [long]$parts[2]) {
                Write-Skip "$Name 已由本副本启动（pid=$($parts[0])），端口 $Port 不重复拉起"
                return $true
            }
        }
    }
    Write-Warn2 "端口 $Port 已被外部进程占用，$Name 跳过启动（绝不抢端口、绝不杀生产进程）"
    return $true
}

function Start-Detached {
    param(
        [string]$Name,
        [string]$Exe,
        # 不能叫 $Args：那是 PowerShell 的自动变量，作参数名会导致传入的参数被吞掉
        [string[]]$ArgList,
        [string]$WorkDir,
        [int]$Port = 0,
        [int]$WaitSeconds = 40
    )
    if ($Port -gt 0 -and (Test-OwnPort $Name $Port)) { return $true }
    if (-not (Test-Path -LiteralPath $Exe)) { Write-Err2 "$Name 缺解释器: $Exe"; return $false }
    if (-not (Test-Path -LiteralPath $WorkDir)) { Write-Err2 "$Name 缺工作目录: $WorkDir"; return $false }

    $argText = ($ArgList | ForEach-Object { Quote-Arg $_ }) -join ' '
    if ($DryRun) { Write-Step "<干跑> $Name : `"$Exe`" $argText   (cwd=$WorkDir)"; return $true }

    $out = Join-Path $TmpDir ("portable-$Name.out")
    $err = Join-Path $TmpDir ("portable-$Name.err")
    # PS 5.1 的 Start-Process 不允许 stdout/stderr 指向同一文件
    $proc = Start-Process -FilePath $Exe -ArgumentList $argText -WorkingDirectory $WorkDir `
        -WindowStyle Hidden -PassThru -RedirectStandardOutput $out -RedirectStandardError $err
    Save-Pid $Name $proc.Id
    if ($Port -gt 0) {
        if (Wait-Port $Port $WaitSeconds) { Write-Ok "$Name 已监听 $Port (pid=$($proc.Id))"; return $true }
        Write-Err2 "$Name 未在 ${WaitSeconds}s 内监听 $Port，日志：$out / $err"
        return $false
    }
    Write-Ok "$Name 已启动 (pid=$($proc.Id))"
    return $true
}

# ------------------------------------------------------------- 1) 便携 PG
Write-Step '--- 1/6 便携 PostgreSQL ---'
$pgCtl = Join-Path $PgBin 'pg_ctl.exe'
$psql = Join-Path $PgBin 'psql.exe'
if (-not (Test-Path -LiteralPath $pgCtl)) {
    Write-Err2 "缺 pg_ctl.exe: $PgBin（请先跑 -Stage runtimes）"
} elseif (-not $DryRun) {
    if (-not (Test-Path -LiteralPath (Join-Path $PgData 'PG_VERSION'))) {
        $initdb = Join-Path $PgBin 'initdb.exe'
        Write-Step "首次启动，initdb -> $PgData"
        & $initdb -D $PgData -U $PgUser -A trust --encoding=UTF8 2>&1 |
            ForEach-Object { Write-Host "  $_" }
        if ($LASTEXITCODE -ne 0) { throw "initdb 失败（exit=$LASTEXITCODE）" }
    }
    $pgLog = Join-Path $TmpDir 'portable-pg.log'
    & $pgCtl -D $PgData status 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        & $pgCtl -D $PgData -l $pgLog -o "-p $PgPort -h 127.0.0.1" start 2>&1 |
            ForEach-Object { Write-Host "  $_" }
    }
    if (-not (Wait-Port $PgPort 30)) { throw "便携 PG 未在 30s 内监听 $PgPort，见 $pgLog" }
    $dbExists = & $psql -h 127.0.0.1 -p $PgPort -U $PgUser -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$PgDb'" 2>$null
    if (-not $dbExists) {
        $createdb = Join-Path $PgBin 'createdb.exe'
        & $createdb -h 127.0.0.1 -p $PgPort -U $PgUser $PgDb 2>&1 | ForEach-Object { Write-Host "  $_" }
    }
    Write-Ok "便携 PG 就绪 127.0.0.1:$PgPort / $PgDb"
    Write-Step '若数据库为空，请另跑 scripts\bundle_data.ps1 灌入快照'
} else {
    Write-Step "<干跑> 跳过 initdb / pg_ctl start（$PgData）"
}

# ------------------------------------------------- 2) nginx 配置（含 -t 校验）
Write-Step '--- 2/6 nginx 配置展开 ---'
$startNginx = (Get-Cfg 'START_NGINX' '1') -eq '1'
$confScript = Join-Path $Root 'write_nginx_conf.ps1'
if ($startNginx -and -not $SkipNginxConf) {
    if (-not $DryRun) {
        if (-not (Test-Path -LiteralPath $confScript)) { throw "缺 $confScript（请先跑 -Stage config）" }
        & (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe') `
            -NoProfile -ExecutionPolicy Bypass -File $confScript
        if ($LASTEXITCODE -ne 0) { throw 'write_nginx_conf.ps1 失败，未继续启动' }
    } else { Write-Step '<干跑> 跳过 write_nginx_conf.ps1' }
}

# ------------------------------------------------------------- 3) my_app 后端
Write-Step '--- 3/6 my_app 后端 ---'
$null = Start-Detached -Name 'backend' -Exe $PyExe `
    -ArgList @('-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', [string]$BePort) `
    -WorkDir $MyAppDir -Port $BePort -WaitSeconds 45

# ------------------------------------------------------------- 4) my_app 前端
Write-Step '--- 4/6 my_app 前端（vite preview） ---'
$viteCli = Join-Path $FeDir 'node_modules\vite\bin\vite.js'
$null = Start-Detached -Name 'frontend' -Exe $NodeExe `
    -ArgList @($viteCli, 'preview', '--host', '127.0.0.1', '--port', [string]$FePort, '--strictPort') `
    -WorkDir $FeDir -Port $FePort -WaitSeconds 30

# ----------------------------------------------------------------- 5) 门户
Write-Step '--- 5/6 统一门户 + 可选服务 ---'
if ($PortalRoot) {
    $tsxCli = Join-Path $PortalRoot 'node_modules\tsx\dist\cli.mjs'
    $null = Start-Detached -Name 'portal' -Exe $NodeExe `
        -ArgList @($tsxCli, 'server/index.ts') -WorkDir $PortalRoot -Port $PortalPort -WaitSeconds 30
} else {
    Write-Warn2 '未找到门户目录（liberia-noc_soc-*），门户步骤跳过'
}

if ((Get-Cfg 'START_WA_ANALYSIS' '0') -eq '1') {
    $waDir = Join-Path $Root 'liberia-noc_soc-数据看板统一门户\scripts\whatsapp_analysis'
    $waCli = Join-Path $waDir 'node_modules\tsx\dist\cli.mjs'
    if (Test-Path -LiteralPath $waCli) {
        $null = Start-Detached -Name 'wa_analysis' -Exe $NodeExe `
            -ArgList @($waCli, 'server/index.ts') -WorkDir $waDir -Port $WaAnalysisPort -WaitSeconds 25
    } else { Write-Warn2 '9268 分析服务依赖缺失，跳过' }
}

if ((Get-Cfg 'START_WA_BOT' '0') -eq '1') {
    Write-Warn2 'START_WA_BOT=1：会使用副本里的 WhatsApp 登录态接管会话，务必确认已在目标机重新扫码'
    $null = Start-Detached -Name 'wa_bot' -Exe $NodeExe `
        -ArgList @('--env-file-if-exists=.env', 'src/index.js') -WorkDir $BotDir -WaitSeconds 0
}

# 问答助手 9269 不在这里启动：由 my_app 后端 portal_qa_ctl.py 在首次提问时按需
# DETACHED 拉起（PORTAL_QA_NODE 已指向副本自带 node），这里只需把环境变量备好。

# ----------------------------------------------------------------- 6) nginx
Write-Step '--- 6/6 nginx ---'
if ($startNginx) {
    if (Test-OwnPort 'nginx' $HttpPort) { }
    elseif ($DryRun) { Write-Step '<干跑> 跳过 nginx 启动' }
    elseif (-not (Test-Path -LiteralPath $NginxExe)) { Write-Err2 "缺 $NginxExe" }
    else {
        # Windows nginx 自带 daemon 化，-p 指到副本自己的目录才能正确解析 logs/conf
        & $NginxExe -p "$NginxDir\" -c 'conf/nginx.conf' 2>&1 | ForEach-Object { Write-Host "  $_" }
        $nginxPidFile = Join-Path $NginxDir 'logs\nginx.pid'
        if (Wait-Port $HttpPort 15) {
            if (Test-Path -LiteralPath $nginxPidFile) {
                $npid = ([System.IO.File]::ReadAllText($nginxPidFile)).Trim()
                if ($npid -match '^\d+$') { Save-Pid 'nginx' ([int]$npid) }
            }
            Write-Ok "nginx 已监听 $HttpPort"
        } else { Write-Err2 "nginx 未在 15s 内监听 $HttpPort，见 $NginxDir\logs\error.log" }
    }
} else { Write-Skip 'START_NGINX=0，不启动 nginx' }

# ------------------------------------------------------------------ 状态汇总
Write-Host ''
Write-Host '==================== 副本服务状态 ====================' -ForegroundColor Cyan
$ports = [ordered]@{
    'nginx' = $HttpPort; 'my_app 前端' = $FePort; 'my_app 后端' = $BePort
    '统一门户' = $PortalPort; '便携 PG' = $PgPort
}
foreach ($k in $ports.Keys) {
    $up = Test-PortListening ([int]$ports[$k])
    Write-Host ('  {0,-14} {1,-6} {2}' -f $k, $ports[$k], $(if ($up) { 'LISTENING' } else { 'not listening' })) `
        -ForegroundColor $(if ($up) { 'Green' } else { 'Yellow' })
}
Write-Host ''
Write-Host '  入口（HTTP，副本无证书）：' -ForegroundColor White
Write-Host ('    http://localhost:{0}/                 根导航' -f $HttpPort)
Write-Host ('    http://localhost:{0}/myapp/           Data Insight MVP' -f $HttpPort)
Write-Host ('    http://localhost:{0}/uniplam/         统一门户' -f $HttpPort)
Write-Host ('    http://localhost:{0}/v3/olbrportal/  问答助手挂件' -f $HttpPort)
Write-Host ''
Write-Host '  停止：双击副本根目录 stop.bat（只停本副本进程）' -ForegroundColor DarkGray
$sw.Stop()
Write-Ok ("start_all 完成，耗时 {0:N1} 秒{1}" -f $sw.Elapsed.TotalSeconds, $(if ($DryRun) { '（干跑）' } else { '' }))
