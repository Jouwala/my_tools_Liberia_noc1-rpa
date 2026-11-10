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
    source      同步四样源码子树（robocopy /E，绝不 /MIR —— 只增不删）
    prune       清掉旧全量拷贝残留的 AI 元数据/缓存/日志（规则见 manifest.prune）
    nodemodules 精确拷贝各子项目 node_modules
    runtimes    自带 Python312 / Node / PostgreSQL16(bin,lib,share)
    nginx       拷 nginx.exe 与地图瓦片 html\
    config      铺 .env / 启停薄壳 / nginx 模板 / 根导航页 / scripts\start_all.ps1 等（见 portable\ 模板）
    data        不在此脚本内：bundle_data.ps1 铺到副本 scripts\ 后单独跑（pg_dump + initdb + restore）

  用法：
    powershell -NoProfile -File scripts\build_olbr_portable.ps1 -Stage source -DryRun
    powershell -NoProfile -File scripts\build_olbr_portable.ps1 -Stage all
  =============================================================================
#>
[CmdletBinding()]
param(
    [string]$MainRepo = 'D:\01_RPA',
    [string]$CopyRoot = 'D:\01_olbr_portal',
    [ValidateSet('all', 'quarantine', 'source', 'prune', 'nodemodules', 'runtimes', 'nginx', 'config')]
    [string]$Stage = 'all',
    [switch]$DryRun,
    [switch]$SkipQuarantineCheck,
    [switch]$SkipPathFix
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
        'scripts', 'start.bat', 'stop.bat', 'write_nginx_conf.ps1', 'nginx.conf.template',
        '部署说明.md', '.env', 'AGENTS.md', $qName, 'TMP'
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

# ------------------------------------------------------------- post-sync fixups
# The source stage copies Task/my_app and the portal subtree verbatim, so two
# scripts that were hand-fixed for the isolated copy get reverted to D:\01_RPA
# paths on every sync:
#     Task\my_app\monitor_fixes\nginx_monitor.ps1  (NginxExe/NginxDir/Port/Log/State)
#     <portal>\rotate_nginx_logs.ps1                ($Prefix)
#
# That is harmless while the copy is idle, but at cutover the nginx watchdog
# would probe D:\01_RPA\nginx-1.28.0\nginx.exe (port 80) instead of the copy's
# own instance and could spawn a second nginx fighting for the port.
#
# Running it automatically here means "sync the source" is always a complete
# operation -- no separate manual step to remember.
function Invoke-PathFix {
    if ($SkipPathFix) {
        Write-Log '  [跳过] -SkipPathFix 已指定' 'DarkYellow'
        return
    }
    if ($DryRun) {
        Write-Log '  <干跑> 未执行 post_sync_fix_paths.ps1' 'Cyan'
        return
    }
    $fixer = Join-Path $CopyRoot 'scripts\post_sync_fix_paths.ps1'
    if (-not (Test-Path -LiteralPath $fixer)) {
        Write-Log '  [跳过] 副本里没有 scripts\post_sync_fix_paths.ps1（先跑一次 -Stage config）' 'DarkYellow'
        return
    }
    Write-Log '  [修路径] post_sync_fix_paths.ps1（把副本本地路径写回）' 'Cyan'
    # Never let the fixup abort the sync: a failure here must not leave the copy
    # half-updated. The script itself is idempotent, so it is safe to re-run.
    & powershell -NoProfile -ExecutionPolicy Bypass -File $fixer -CopyRoot $CopyRoot 2>&1 |
        ForEach-Object { Write-Log "    $_" 'DarkGray' }
    if ($LASTEXITCODE -ne 0) {
        Write-Log "  [警告] post_sync_fix_paths.ps1 退出码 $LASTEXITCODE —— 请手工核对副本的 nginx 路径" 'Yellow'
    }
}

# --------------------------------------------------------------------- prune
# robocopy /E 只增不删：从 10-16 全量旧拷贝升级时，排除规则只挡住「别再复制」，
# 已经躺在副本里的 .workbuddy-ai / __pycache__ / 日志不会自己消失。本阶段按
# manifest.prune 幂等清理；跳过 node_modules/runtime（依赖本体），protect_rel
# 里的 .env / portal-default.json 是 config 阶段生成的运行时配置，绝不删。
function Invoke-Prune {
    Write-Log '=== 阶段 prune：清掉旧全量拷贝残留（robocopy /E 只增不删） ===' 'Cyan'
    $p = $manifest.prune
    if (-not $p) { Write-Log '  [跳过] manifest 未配置 prune' 'DarkYellow'; return }

    $protect = @{}
    foreach ($r in $p.protect_rel) { $protect[$r.Replace('\', '/')] = $true }

    $removed = 0
    $bytes = [long]0
    foreach ($sr in $p.scan_roots) {
        $base = Join-Path $CopyRoot ($sr -replace '/', '\')
        if (-not (Test-Path -LiteralPath $base)) { continue }
        $stack = New-Object System.Collections.Stack
        $stack.Push($base)
        while ($stack.Count -gt 0) {
            $cur = [string]$stack.Pop()
            try { $entries = @(Get-ChildItem -LiteralPath $cur -Force -ErrorAction Stop) }
            catch { Write-Log "  [跳过不可读] $cur" 'DarkYellow'; continue }
            foreach ($e in $entries) {
                if ($e.Attributes -band [IO.FileAttributes]::ReparsePoint) { continue }
                $rel = $e.FullName.Substring($CopyRoot.Length).TrimStart([char[]]@('\', '/')).Replace('\', '/')
                if ($protect.ContainsKey($rel)) { continue }

                if ($e.PSIsContainer) {
                    if ($p.skip_dirs -contains $e.Name) { continue }
                    if ($p.prune_dirs -contains $e.Name) {
                        $sz = (Get-ChildItem -LiteralPath $e.FullName -Recurse -Force -File -ErrorAction SilentlyContinue |
                               Measure-Object -Property Length -Sum).Sum
                        if (-not $sz) { $sz = 0 }
                        if ($DryRun) {
                            Write-Log ("  <干跑删目录> {0}  ({1:N2} MB)" -f $rel, ($sz / 1MB)) 'Cyan'
                        } else {
                            Remove-Item -LiteralPath $e.FullName -Recurse -Force -ErrorAction Stop
                            Write-Log ("  [删目录] {0}  ({1:N2} MB)" -f $rel, ($sz / 1MB)) 'Green'
                        }
                        $removed++
                        $bytes += [long]$sz
                        continue
                    }
                    $stack.Push($e.FullName)
                } else {
                    $hit = $false
                    foreach ($pat in $p.prune_files) {
                        if ($e.Name -like $pat) { $hit = $true; break }
                    }
                    if ($hit) {
                        if ($DryRun) { Write-Log "  <干跑删文件> $rel" 'Cyan' }
                        else { Remove-Item -LiteralPath $e.FullName -Force -ErrorAction Stop }
                        $removed++
                        $bytes += [long]$e.Length
                    }
                }
            }
        }
    }
    Write-Log ("  清理 {0} 项 / {1:N2} MB{2}" -f $removed, ($bytes / 1MB), $(if ($DryRun) { ' <干跑，未改动>' } else { '' })) 'Green'
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
    # 根目录模板：start.bat / stop.bat 只是薄壳，真正逻辑在 scripts\start_all.ps1
    $files = @('start.bat', 'stop.bat', 'write_nginx_conf.ps1',
               'nginx.conf.template', '部署说明.md')
    foreach ($f in $files) {
        $s = Join-Path $tpl $f
        if (-not (Test-Path -LiteralPath $s)) { Write-Log "  [待写] 模板缺失: $f" 'DarkYellow'; continue }
        $d = Join-Path $CopyRoot $f
        if (-not $DryRun) { Copy-Item -LiteralPath $s -Destination $d -Force }
        Write-Log "  [模板] $f" 'Green'
    }

    # 根的 .env 只在首次生成：使用者改过端口/密钥后，重跑 config 不得覆盖
    $envDst = Join-Path $CopyRoot '.env'
    $envTpl = Join-Path $tpl 'env_template.txt'
    if (Test-Path -LiteralPath $envTpl) {
        if (Test-Path -LiteralPath $envDst) { Write-Log '  [保留] .env 已存在，未覆盖' 'DarkYellow' }
        else {
            if (-not $DryRun) { Copy-Item -LiteralPath $envTpl -Destination $envDst -Force }
            Write-Log '  [配置] .env（由 env_template.txt 生成）' 'Green'
        }
    } else { Write-Log '  [待写] 模板缺失: env_template.txt' 'DarkYellow' }

    # 根导航页铺到 nginx 的 html\ 下（nginx.conf 的 location / 用 root html）
    $indexTpl = Join-Path $tpl 'nginx_index.html'
    $htmlDir = Join-Path $CopyRoot 'nginx-1.28.0\html'
    if (Test-Path -LiteralPath $indexTpl) {
        if (-not (Test-Path -LiteralPath $htmlDir)) {
            if (-not $DryRun) { New-Item -ItemType Directory -Path $htmlDir -Force | Out-Null }
        }
        if (-not $DryRun) { Copy-Item -LiteralPath $indexTpl -Destination (Join-Path $htmlDir 'index.html') -Force }
        Write-Log '  [导航页] nginx-1.28.0\html\index.html' 'Green'
    } else { Write-Log '  [待写] 模板缺失: nginx_index.html' 'DarkYellow' }

    # 副本 scripts\：start.bat / stop.bat 只调这里的 start_all.ps1 / stop_all.ps1
    $scriptsDst = Join-Path $CopyRoot 'scripts'
    if (-not $DryRun) {
        if (-not (Test-Path -LiteralPath $scriptsDst)) { New-Item -ItemType Directory -Path $scriptsDst -Force | Out-Null }
    }
    foreach ($f in @('start_all.ps1', 'stop_all.ps1', 'bundle_data.ps1', 'env_template.txt', 'post_sync_fix_paths.ps1')) {
        $s = Join-Path $tpl $f
        if (-not (Test-Path -LiteralPath $s)) { Write-Log "  [待写] 脚本缺失: scripts\$f" 'DarkYellow'; continue }
        if (-not $DryRun) { Copy-Item -LiteralPath $s -Destination (Join-Path $scriptsDst $f) -Force }
        Write-Log "  [脚本] scripts\$f" 'Green'
    }

    # 副本 my_portal\：一排可双击的入口（纯 %~dp0 相对路径，换盘符仍有效）。
    # 与桌面「my_portal」不是一回事：那套 .lnk 写死 D:\01_RPA 且管的是生产实例。
    $lnkSrc = Join-Path $tpl 'my_portal'
    $lnkDst = Join-Path $CopyRoot 'my_portal'
    if (Test-Path -LiteralPath $lnkSrc) {
        $linkFiles = @(Get-ChildItem -LiteralPath $lnkSrc -File)
        if (-not $DryRun) {
            if (-not (Test-Path -LiteralPath $lnkDst)) {
                New-Item -ItemType Directory -Path $lnkDst -Force | Out-Null
            }
            foreach ($lf in $linkFiles) {
                Copy-Item -LiteralPath $lf.FullName -Destination (Join-Path $lnkDst $lf.Name) -Force
            }
        }
        Write-Log "  [入口夹] my_portal\（$($linkFiles.Count) 个文件）" 'Green'
    } else { Write-Log '  [待写] 模板缺失: my_portal\' 'DarkYellow' }
}

# ---------------------------------------------------------------------- main
Write-Log "主仓库 = $MainRepo"
Write-Log "副本   = $CopyRoot"
Write-Log "阶段   = $Stage   干跑 = $DryRun"
Write-Log "日志   = $logFile"
if (-not (Test-Path -LiteralPath $CopyRoot)) { throw "副本根目录不存在: $CopyRoot" }

$stages = if ($Stage -eq 'all') { @('quarantine', 'source', 'prune', 'nodemodules', 'runtimes', 'nginx', 'config') } else { @($Stage) }
$sw = [System.Diagnostics.Stopwatch]::StartNew()
foreach ($s in $stages) {
    switch ($s) {
        'quarantine' { Invoke-Quarantine }
        'source' { Invoke-Source }
        'prune' { Invoke-Prune }
        'nodemodules' { Invoke-NodeModules }
        'runtimes' { Invoke-Runtimes }
        'nginx' { Invoke-Nginx }
        'config' { Invoke-Config }
    }
}
# The path fixup runs after every stage that can overwrite the copy-local paths.
# Only 'source' copies those two files; 'config' re-deploys the fixer itself.
if ($stages -contains 'source' -or $stages -contains 'config') {
    Write-Log '=== 收尾：把副本本地路径写回 ===' 'Cyan'
    Invoke-PathFix
}
$sw.Stop()
Write-Log ("完成阶段 {0}，耗时 {1:N1} 秒{2}" -f ($stages -join ','), $sw.Elapsed.TotalSeconds, $(if ($DryRun) { '（干跑，未改动）' } else { '' })) 'Cyan'
Write-Log '数据快照请另跑: powershell -NoProfile -File scripts\portable\bundle_data.ps1'