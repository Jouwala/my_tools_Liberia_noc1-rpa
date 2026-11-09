<#
  build_olbr_portable.ps1 —— 把 D:\01_RPA 打包成可换机离线运行的 D:\01_olbr_portal
  =============================================================================
  只保留四样：统一门户 / WhatsApp bot / 门户问答助手挂件 / my_app，及其运行时。
  清单真相源：scripts\portable\manifest.json

  与旧 sync_one_click.ps1 的区别：旧版是 2026-10-16 硬编码的 541 文件清单，
  已过期且混入 MTN_Comsal/ORANGE/RAN/.agnes 缓存等无关内容。本版改为
  「白名单子树 + 排除规则」，并额外自带 Python/Node/PostgreSQL/nginx 运行时。

  阶段（可单独跑，便于逐步验证）：
    quarantine  把副本里不在保留清单的目录移入 _quarantine_<日期>\（可逆）
    source      同步四样源码子树（robocopy /E，绝不 /MIR）
    nodemodules 精确拷贝各子项目 node_modules
    runtimes    自带 Python312 / Node / PostgreSQL16(bin,lib,share)
    nginx       拷 nginx.exe 与地图瓦片 html\
    config      生成副本侧 .env / 启动脚本 / nginx conf（见 portable\ 模板）
    data        由 portable\bundle_data.ps1 单独负责（pg_dump + initdb + restore）

  用法：
    powershell -NoProfile -File scripts\build_olbr_portable.ps1 -Stage source -DryRun
    powershell -NoProfile -File scripts\build_olbr_portable.ps1 -Stage all
  =============================================================================
#>
[CmdletBinding()]
param(
    [string]$MainRepo = 'D:\01_RPA',
    [string]$CopyRoot = 'D:\01_olbr_portal',
    [ValidateSet('all', 'quarantine', 'source', 'nodemodules', 'runtimes', 'nginx', 'config')]
    [string]$Stage = 'all',
    [switch]$DryRun,
    [switch]$SkipQuarantineCheck
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$manifestPath = Join-Path $PSScriptRoot 'portable\manifest.json'
$manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$logDir = Join-Path $MainRepo 'TMP'
if (-not (Test-Path -LiteralPath $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$logFile = Join-Path $logDir ("_build_portable_{0}_{1}.log" -f $Stage, $stamp)

function Write-Log {
    param([string]$Msg, [string]$Color = 'Gray')
    $line = '[{0}] {1}' -f (Get-Date -Format 'HH:mm:ss'), $Msg
    Write-Host $line -ForegroundColor $Color
    Add-Content -LiteralPath $logFile -Value $line -Encoding UTF8
}

# robocopy 退出码 0..7 是成功（位掩码：1=有复制 2=有额外 4=有不匹配），>=8 才是失败
function Invoke-Robocopy {
    param([string]$Src, [string]$Dst, [string[]]$ExtraArgs, [string]$Label)
    if (-not (Test-Path -LiteralPath $Src)) {
        Write-Log "  [跳过] 源不存在: $Src" 'DarkYellow'
        return $false
    }
    $argv = @($Src, $Dst, '/E', '/COPY:DAT', '/DCOPY:DAT', '/R:1', '/W:1', '/NFL', '/NDL', '/NJH', '/NP', '/MT:8')
    if ($DryRun) { $argv += '/L' }
    if ($ExtraArgs) { $argv += $ExtraArgs }
    $rcLog = Join-Path $logDir ("_rc_{0}_{1}.log" -f ($Label -replace '[^\w]', '_'), $stamp)
    $argv += @("/LOG:$rcLog", '/TEE')
    & robocopy @argv | Out-Null
    $code = $LASTEXITCODE
    if ($code -ge 8) {
        Write-Log "  [失败] robocopy 退出码 $code ($Label)，详见 $rcLog" 'Red'
        throw "robocopy failed: $Label exit=$code"
    }
    Write-Log ("  [OK] {0} (rc={1}){2}" -f $Label, $code, $(if ($DryRun) { ' <干跑>' } else { '' })) 'Green'
    return $true
}

function Get-ExcludeArgs {
    param($Item, [string]$SrcRoot)
    $args = @()
    $xd = @()
    foreach ($d in $Item.exclude_root) { $xd += (Join-Path $SrcRoot $d) }
    foreach ($d in $Item.exclude_any) { $xd += $d }
    if ($xd.Count) { $args += '/XD'; $args += $xd }
    if ($Item.exclude_files -and $Item.exclude_files.Count) { $args += '/XF'; $args += $Item.exclude_files }
    return $args
}

# ---------------------------------------------------------------- quarantine
function Invoke-Quarantine {
    Write-Log '=== 阶段 quarantine：无关目录移入隔离区（可逆） ===' 'Cyan'
    $qName = $manifest.quarantine_name
    $qRoot = Join-Path $CopyRoot $qName
    $keepRoot = @(
        'liberia-noc_soc-数据看板统一门户', 'Task', 'nginx-1.28.0', 'runtime',
        'scripts', 'start.bat', 'stop.bat', 'write_nginx_conf.ps1', '部署说明.md',
        'AGENTS.md', $qName, 'TMP'
    )
    # Task 下只保留三样
    $keepTask = @($manifest.keep_task_children)

    $moves = @()
    foreach ($e in (Get-ChildItem -LiteralPath $CopyRoot -Force)) {
        if ($keepRoot -contains $e.Name) { continue }
        $moves += [pscustomobject]@{ From = $e.FullName; To = (Join-Path $qRoot $e.Name); Kind = 'root' }
    }
    $taskRoot = Join-Path $CopyRoot 'Task'
    if (Test-Path -LiteralPath $taskRoot) {
        foreach ($e in (Get-ChildItem -LiteralPath $taskRoot -Force)) {
            if ($keepTask -contains $e.Name) { continue }
            $rel = 'Task\' + $e.Name
            $moves += [pscustomobject]@{ From = $e.FullName; To = (Join-Path $qRoot $rel); Kind = 'task' }
        }
    }

    Write-Log ("  待移动 {0} 项 -> {1}" -f $moves.Count, $qRoot)
    foreach ($m in $moves) { Write-Log ("    {0}" -f $m.From.Replace($CopyRoot, '')) }

    if (-not $SkipQuarantineCheck) {
        Write-Log '  检查保留源码是否引用了待隔离目录（git grep --untracked，单次扫描）...'
        $names = @($moves | ForEach-Object { Split-Path $_.From -Leaf } | Select-Object -Unique |
                   Where-Object { $_ -notin @('my_app', 'whatsapp-kb-bot', '_fe_dist') })
        if ($names.Count) {
            # 只查带路径分隔或明显是目录引用的写法，避免命中同名业务字符串（如群名里的 ORANGE）
            $patterns = @($names | ForEach-Object { 'Task/' + $_; 'Task\' + $_ })
            $gitArgs = @('-C', $MainRepo, '-c', 'core.quotepath=off', 'grep', '-l', '-I', '--untracked')
            foreach ($p in $patterns) { $gitArgs += @('-e', $p) }
            $gitArgs += '--'
            foreach ($sub in $manifest.keep_subtrees) { $gitArgs += ($sub.src -replace '\\', '/') }
            $found = & git @gitArgs 2>$null
            if ($found) {
                Write-Log '  [警告] 保留源码里出现对待隔离目录的路径引用，请人工确认：' 'Yellow'
                foreach ($f in ($found | Select-Object -First 25)) { Write-Log "    $f" 'Yellow' }
                Write-Log '  确认引用无关后加 -SkipQuarantineCheck 重跑。本次不移动。' 'Yellow'
                return
            }
        }
        Write-Log '  引用检查通过' 'Green'
    }

    if ($DryRun) { Write-Log '  <干跑> 未移动' 'Cyan'; return }
    foreach ($m in $moves) {
        $parent = Split-Path $m.To -Parent
        if (-not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
        if (Test-Path -LiteralPath $m.To) { Write-Log "  [跳过] 隔离区已存在同名: $($m.To)" 'DarkYellow'; continue }
        Move-Item -LiteralPath $m.From -Destination $m.To -Force
        Write-Log "  [移动] $($m.From.Replace($CopyRoot,'')) -> $qName\" 'Green'
    }
}

# -------------------------------------------------------------------- source
function Invoke-Source {
    Write-Log '=== 阶段 source：同步四样源码子树 ===' 'Cyan'
    foreach ($sub in $manifest.keep_subtrees) {
        $src = Join-Path $MainRepo ($sub.src -replace '/', '\')
        $dst = Join-Path $CopyRoot ($sub.dst -replace '/', '\')
        Write-Log ("  {0}  [{1}]" -f $sub.src, $sub.why)
        $ex = Get-ExcludeArgs $sub $src
        Invoke-Robocopy -Src $src -Dst $dst -ExtraArgs $ex -Label $sub.dst | Out-Null
    }
    foreach ($sub in $manifest.extra_copies) {
        $src = Join-Path $MainRepo ($sub.src -replace '/', '\')
        $dst = Join-Path $CopyRoot ($sub.dst -replace '/', '\')
        Write-Log ("  {0}  [{1}]" -f $sub.src, $sub.why)
        $ex = Get-ExcludeArgs $sub $src
        Invoke-Robocopy -Src $src -Dst $dst -ExtraArgs $ex -Label $sub.dst | Out-Null
    }
    foreach ($f in $manifest.keep_root_files) {
        $src = Join-Path $MainRepo $f
        if (Test-Path -LiteralPath $src) {
            if (-not $DryRun) { Copy-Item -LiteralPath $src -Destination (Join-Path $CopyRoot $f) -Force }
            Write-Log "  [根文件] $f" 'Green'
        }
    }
}

# --------------------------------------------------------------- nodemodules
function Invoke-NodeModules {
    Write-Log '=== 阶段 nodemodules：精确拷贝各子项目依赖 ===' 'Cyan'
    foreach ($nm in $manifest.runtime_node_modules) {
        $src = Join-Path $MainRepo ($nm.src -replace '/', '\')
        $dst = Join-Path $CopyRoot ($nm.dst -replace '/', '\')
        if (-not (Test-Path -LiteralPath $src)) {
            if ($nm.optional) { Write-Log "  [可选跳过] $($nm.src)" 'DarkYellow'; continue }
            Write-Log "  [缺失] $($nm.src) —— 需在主仓库先 npm install" 'Red'
            continue
        }
        Write-Log ("  {0}  [{1}]" -f $nm.src, $nm.why)
        Invoke-Robocopy -Src $src -Dst $dst -ExtraArgs @('/XD', '__pycache__', '/XF', '*.pyc') -Label $nm.dst | Out-Null
    }
}

# ------------------------------------------------------------------ runtimes
function Invoke-Runtimes {
    Write-Log '=== 阶段 runtimes：自带 Python / Node / PostgreSQL ===' 'Cyan'
    foreach ($rt in $manifest.bundled_runtimes) {
        $src = $rt.src -replace '/', '\'
        $dst = Join-Path $CopyRoot ($rt.dst -replace '/', '\')
        Write-Log ("  {0} -> {1}  [{2}]" -f $src, $rt.dst, $rt.why)
        if ($rt.only_dirs) {
            # PG：只取 bin/lib/share，绝不拷生产 data 目录
            foreach ($d in $rt.only_dirs) {
                $s = Join-Path $src $d
                Invoke-Robocopy -Src $s -Dst (Join-Path $dst $d) -ExtraArgs @() -Label "$($rt.dst)_$d" | Out-Null
            }
            continue
        }
        $ex = Get-ExcludeArgs $rt $src
        Invoke-Robocopy -Src $src -Dst $dst -ExtraArgs $ex -Label $rt.dst | Out-Null
    }
}

# --------------------------------------------------------------------- nginx
function Invoke-Nginx {
    Write-Log '=== 阶段 nginx：二进制 + 地图瓦片 ===' 'Cyan'
    $n = $manifest.nginx_from_main
    $src = Join-Path $MainRepo $n.src
    $dst = Join-Path $CopyRoot $n.dst
    foreach ($f in $n.keep_files) {
        $s = Join-Path $src $f
        if (Test-Path -LiteralPath $s) {
            if (-not $DryRun) { Copy-Item -LiteralPath $s -Destination (Join-Path $dst $f) -Force }
            Write-Log "  [文件] $f" 'Green'
        } else { Write-Log "  [缺失] $s" 'Red' }
    }
    foreach ($d in $n.keep_dirs) {
        Invoke-Robocopy -Src (Join-Path $src $d) -Dst (Join-Path $dst $d) -ExtraArgs @() -Label "nginx_$d" | Out-Null
    }
}

# -------------------------------------------------------------------- config
function Invoke-Config {
    Write-Log '=== 阶段 config：铺启动脚本与配置模板 ===' 'Cyan'
    $tpl = Join-Path $PSScriptRoot 'portable'
    $files = @('start.bat', 'stop.bat', 'write_nginx_conf.ps1', 'nginx.conf.template', '部署说明.md')
    foreach ($f in $files) {
        $s = Join-Path $tpl $f
        if (-not (Test-Path -LiteralPath $s)) { Write-Log "  [待写] 模板缺失: $f" 'DarkYellow'; continue }
        $d = Join-Path $CopyRoot $f
        if (-not $DryRun) { Copy-Item -LiteralPath $s -Destination $d -Force }
        Write-Log "  [模板] $f" 'Green'
    }
    $scriptsDst = Join-Path $CopyRoot 'scripts'
    if (-not $DryRun) {
        if (-not (Test-Path -LiteralPath $scriptsDst)) { New-Item -ItemType Directory -Path $scriptsDst -Force | Out-Null }
    }
    foreach ($f in @('bundle_data.ps1', 'env_template.txt')) {
        $s = Join-Path $tpl $f
        if (Test-Path -LiteralPath $s) {
            if (-not $DryRun) { Copy-Item -LiteralPath $s -Destination (Join-Path $scriptsDst $f) -Force }
            Write-Log "  [脚本] scripts\$f" 'Green'
        }
    }
}

# ---------------------------------------------------------------------- main
Write-Log "主仓库 = $MainRepo"
Write-Log "副本   = $CopyRoot"
Write-Log "阶段   = $Stage   干跑 = $DryRun"
Write-Log "日志   = $logFile"
if (-not (Test-Path -LiteralPath $CopyRoot)) { throw "副本根目录不存在: $CopyRoot" }

$stages = if ($Stage -eq 'all') { @('quarantine', 'source', 'nodemodules', 'runtimes', 'nginx', 'config') } else { @($Stage) }
$sw = [System.Diagnostics.Stopwatch]::StartNew()
foreach ($s in $stages) {
    switch ($s) {
        'quarantine' { Invoke-Quarantine }
        'source' { Invoke-Source }
        'nodemodules' { Invoke-NodeModules }
        'runtimes' { Invoke-Runtimes }
        'nginx' { Invoke-Nginx }
        'config' { Invoke-Config }
    }
}
$sw.Stop()
Write-Log ("完成阶段 {0}，耗时 {1:N1} 秒{2}" -f ($stages -join ','), $sw.Elapsed.TotalSeconds, $(if ($DryRun) { '（干跑，未改动）' } else { '' })) 'Cyan'
Write-Log '数据快照请另跑: powershell -NoProfile -File scripts\portable\bundle_data.ps1'