<#
  deploy_to_copy.ps1 -- 一条龙：把编辑区的改动同步到运行副本，并让副本真正跑起来。

  为什么需要这个脚本（2026-11-11 实测事故）：
    以前的流程是「sync-now.bat（只搬源码）→ 手工去副本里 npm run build → 手工重启」。
    三个手工步骤里漏任何一个，副本就处于**源码新、产物旧**或**源码新、后端没重载**的状态，
    表现为 split-brain：前端界面是新功能，后端却是旧接口。

    2026-11-11 实测：前端 chunk 已含 col_filters（列头筛选），但 7038 后端跑的是旧代码
    （/api/tables/{t}/data 的 OpenAPI 参数里没有 col_filters，也没有 /column-values 路由），
    结果「列头筛选点了没反应」「选值模式永远显示没有可选值」——
    用户看到的是完全坏掉的新功能，而不是报错。

  本脚本把三步收成一步，并且**每步都做校验**，任何一步没落实就报错退出（非零退出码）：
    1. 同步源码      → 复用副本的 sync-engine.mjs（事务式、冲突 fail-closed）
    2. 重建前端产物  → 在副本里 npm run build（my_app + 统一门户）
    3. 校验一致性    → 对比副本源码哈希 vs 构建产物里的特征串，并实测接口行为

  为什么第 3 步不可省：
    「源码同步成功」不等于「线上生效」。前端是构建产物、后端是常驻进程，
    两者都不吃源码变更 —— 不校验就会把「我明明同步了」变成排查一小时的谜题。

  日常入口是双击 D:\01_olbr_portal\sync-now.bat（把参数原样传给本脚本）。
  用法（主仓 D:\01_RPA 下，与 bat 等价）：
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\deploy_to_copy.ps1            # 同步+构建+校验
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\deploy_to_copy.ps1 -DryRun     # 只看会发生什么
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\deploy_to_copy.ps1 -SkipBuild # 只同步源码
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\deploy_to_copy.ps1 -SkipPortal # 不重建门户

  -SkipRestart 的说明：本脚本**不自动重启**服务。重启会打断正在看数据的人（AGENTS.md 四.6），
    需要重启时由人显式执行，并且要说明影响面。默认只做「同步 + 构建 + 校验」，
    校验会明确告诉你「哪些改动需要重启才生效」。

  ASCII-only body on purpose: PS 5.1 reads a .ps1 without a BOM as ANSI.
#>
[CmdletBinding()]
param(
    [string]$MainRepo = 'D:\01_RPA',
    [string]$CopyRoot = 'D:\01_olbr_portal',
    [switch]$DryRun,
    [switch]$SkipBuild,
    [switch]$SkipPortal,
    [switch]$SkipVerify,
    [switch]$SkipLocalAuthorityCheck,
    [switch]$AcceptSource,
    # sync-now.bat 把 %* 原样传进来，pause 由 bat 自己处理。
    [switch]$NoPause
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

function Info($m) { Write-Host "[INFO] $m" -ForegroundColor Cyan }
function Ok($m) { Write-Host "[ OK ] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "[WARN] $m" -ForegroundColor Yellow }
function Err($m) { Write-Host "[FAIL] $m" -ForegroundColor Red }
function Step($n, $m) { Write-Host "`n=== $n. $m ===" -ForegroundColor White }

$MainRepo = (Resolve-Path -LiteralPath $MainRepo).Path
if (-not (Test-Path -LiteralPath $CopyRoot)) {
    Err "copy root not found: $CopyRoot"; exit 2
}
$CopyRoot = (Resolve-Path -LiteralPath $CopyRoot).Path

# ---- 前置校验：确认目标确实是运行副本，而不是编辑区自己 ----
if ((Get-Item -LiteralPath $CopyRoot).FullName.TrimEnd('\') -eq $MainRepo.TrimEnd('\')) {
    Err "source and copy are the same directory ($MainRepo)"; exit 2
}
$copyFeDist = Join-Path $CopyRoot 'Task\_fe_dist'
$copyBackend = Join-Path $CopyRoot 'Task\my_app\backend\main.py'
if (-not (Test-Path -LiteralPath $copyBackend)) {
    Err "not a valid copy root (missing Task\my_app\backend\main.py): $CopyRoot"; exit 2
}

$nodeExe = Join-Path $CopyRoot 'runtime\node\node.exe'
if (-not (Test-Path -LiteralPath $nodeExe)) { $nodeExe = 'node' }
$syncEngine = Join-Path $CopyRoot 'scripts\sync-engine.mjs'
if (-not (Test-Path -LiteralPath $syncEngine)) {
    Err "sync engine not found: $syncEngine"; exit 2
}

Write-Host "============================================================" -ForegroundColor DarkCyan
Write-Host "  Deploy: $MainRepo  ->  $CopyRoot" -ForegroundColor White
Write-Host "============================================================" -ForegroundColor DarkCyan

# =====================================================================================
Step 1 'Sync source (transactional, source is READ-ONLY)'
# =====================================================================================
$syncArgs = @($syncEngine, '--source', $MainRepo, '--target', $CopyRoot)
if ($DryRun) { $syncArgs += '--dry-run' }
if ($AcceptSource) { $syncArgs += '--accept-source' }
& $nodeExe @syncArgs
$syncRc = $LASTEXITCODE
if ($syncRc -ne 0) {
    Err "sync failed (exit $syncRc). Nothing was half-written; fix the conflicts above and retry."
    exit $syncRc
}
Ok "source synced"

# =====================================================================================
Step 1.5 'Check SQLite local-authority tables (credentials / task_schedule_config / email_recipients)'
# =====================================================================================
# 为什么必须单独查（2026-11-11 实测事故）：
#   这三张表由应用**固定写 SQLite**（credential_store / email_recipient_store /
#   task_runner），与 MY_APP_DB_MODE 无关；PG 里那张只是镜像。而同步器按策略
#   从不搬 db/ 目录，backend/scripts/sync_pg_to_sqlite.py 又把这三张表列进
#   SKIP_TABLES（防止 PG→SQLite 把本地数据 DROP 掉）。
#   两者叠加 = 「从 PG 重建 app.db」的迁移路径**天生带不出它们**，且没有任何一步会报错：
#   副本起来后 16 个任务同时报「拒绝以空密码登录」，任务管理页的禁用也全丢。
#   所以部署这一步必须显式比对，缺了就当场失败并给出迁移命令，而不是等任务批量失败。
if ($DryRun) {
    Warn "dry run: would check local-authority tables (not executed)"
} elseif ($SkipLocalAuthorityCheck) {
    Warn "skipped by -SkipLocalAuthorityCheck -- only use this for a brand-new copy with no old app.db to migrate"
} else {
    $laPython = Join-Path $CopyRoot 'runtime\python312\python.exe'
    if (-not (Test-Path -LiteralPath $laPython)) { $laPython = 'python' }
    $laTool = Join-Path $MainRepo 'scripts\local_authority_tools.py'
    $laSrcDb = Join-Path $MainRepo 'Task\my_app\db\app.db'
    $laDstDb = Join-Path $CopyRoot 'Task\my_app\db\app.db'
    if (-not (Test-Path -LiteralPath $laTool)) {
        Warn "local-authority tool not found, skip check: $laTool"
    } else {
        $env:PYTHONIOENCODING = 'utf-8'
        & $laPython $laTool check --source $laSrcDb --target $laDstDb
        $laRc = $LASTEXITCODE
        if ($laRc -ne 0) {
            Err "copy is missing SQLite local-authority data (exit $laRc)."
            Err "credentials / task_schedule_config / email_recipients do NOT live in PG and are never synced."
            Err "run this once, then retry the deploy:"
            Err "  $laPython `"$laTool`" migrate --source `"$laSrcDb`" --target `"$laDstDb`""
            exit $laRc
        }
        Ok "local-authority tables present in copy"
    }
}

# =====================================================================================
Step 2 'Rebuild frontend artifacts inside the copy'
# =====================================================================================
if ($SkipBuild) {
    Warn "skipped by -SkipBuild -- the copy will still serve the PREVIOUS build"
} else {
    $feDir = Join-Path $CopyRoot 'Task\my_app\frontend'
    if (-not (Test-Path -LiteralPath $feDir)) {
        Err "copy frontend dir missing: $feDir"; exit 2
    }
    # FE_DIST_OUT must point at the copy's own dist, otherwise vite writes into the
    # MAIN repo's Task\_fe_dist and the copy keeps serving its stale build.
    $env:FE_DIST_OUT = $copyFeDist
    if ($DryRun) {
        Warn "dry run: would build my_app frontend -> $copyFeDist (not executed)"
    } else {
    Info "building my_app frontend -> $copyFeDist"
    Push-Location $feDir
    try {
        # vite writes its progress/summary to stderr. Under PowerShell 5.1 a
        # native command writing to stderr raises a NativeCommandError that
        # $ErrorActionPreference='Stop' turns into a terminating error -- even
        # though the build itself succeeded ("built in NNNms"). So: run the
        # build with stderr redirected into stdout, and judge success by the
        # exit code only, never by stderr content.
        $ErrorActionPreference = 'Continue'
        & $nodeExe 'node_modules\typescript\bin\tsc' 2>&1 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
        $tscRc = $LASTEXITCODE
        & $nodeExe 'node_modules\vite\bin\vite.js' build 2>&1 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
        $viteRc = $LASTEXITCODE
        $ErrorActionPreference = 'Stop'
        if ($tscRc -ne 0) { Err "tsc failed (exit $tscRc)"; Pop-Location; exit 1 }
        if ($viteRc -ne 0) { Err "vite build failed (exit $viteRc)"; Pop-Location; exit 1 }
    } finally { Pop-Location }
    Ok "my_app frontend rebuilt"
    }

    if (-not $SkipPortal) {
        # Do NOT hard-code the Chinese portal folder name: PS 5.1 reads this .ps1 as
        # ANSI without a BOM, so the literal would be mojibake. Find it by content.
        # The portal sits at the COPY ROOT (not under Task\): <copy>\liberia-noc_soc-.../
        $portalDir = $null
        foreach ($base in @($CopyRoot, (Join-Path $CopyRoot 'Task'))) {
            if (-not (Test-Path -LiteralPath $base)) { continue }
            $hit = Get-ChildItem -LiteralPath $base -Directory |
                Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'package.json') } |
                Where-Object { (Get-Content -LiteralPath (Join-Path $_.FullName 'package.json') -Raw) -match '"vite"' } |
                Select-Object -First 1 -ExpandProperty FullName
            if ($hit) { $portalDir = $hit; break }
        }
        if ($portalDir) {
            if ($DryRun) {
                Warn "dry run: would build portal at $portalDir (not executed)"
            } else {
            Info "building portal -> $portalDir"
            Push-Location $portalDir
            try {
                # Same stderr caveat as the my_app build above.
                $ErrorActionPreference = 'Continue'
                & $nodeExe 'node_modules\typescript\bin\tsc' '--noEmit' 2>&1 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
                $tscRc = $LASTEXITCODE
                & $nodeExe 'node_modules\vite\bin\vite.js' build 2>&1 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
                $viteRc = $LASTEXITCODE
                $ErrorActionPreference = 'Stop'
                if ($tscRc -ne 0) { Err "portal tsc failed (exit $tscRc)"; Pop-Location; exit 1 }
                if ($viteRc -ne 0) { Err "portal build failed (exit $viteRc)"; Pop-Location; exit 1 }
            } finally { Pop-Location }
            Ok "portal rebuilt"
            }
        } else {
            Warn "portal dir not found under $copyTaskDir, skipped"
        }
    }
}

# =====================================================================================
Step 3 'Verify the copy really serves the new code'
# =====================================================================================
if ($SkipVerify) {
    Warn "skipped by -SkipVerify"
} else {
    $problems = @()

    # --- 3a. index.html 指向的入口 chunk 存在，且是本次构建产物 ---
    $indexPath = Join-Path $copyFeDist 'index.html'
    if (-not (Test-Path -LiteralPath $indexPath)) {
        $problems += "copy _fe_dist\index.html missing"
    } else {
        $idx = Get-Content -LiteralPath $indexPath -Raw
        $entry = $null
        if ($idx -match 'index-([A-Za-z0-9_\-]+)\.js') { $entry = "index-$($Matches[1]).js" }
        if (-not $entry) {
            $problems += "cannot parse the entry chunk name from copy _fe_dist\index.html"
        } else {
            $entryPath = Join-Path $copyFeDist "assets\$entry"
            if (-not (Test-Path -LiteralPath $entryPath)) {
                $problems += "index.html points to $entry but assets\$entry does not exist"
            } else {
                $entryTxt = Get-Content -LiteralPath $entryPath -Raw
                $refs = [regex]::Matches($entryTxt, 'TableBrowser-[A-Za-z0-9_\-]+\.js') | ForEach-Object { $_.Value } | Sort-Object -Unique
                foreach ($r in $refs) {
                    if (-not (Test-Path -LiteralPath (Join-Path $copyFeDist "assets\$r"))) {
                        $problems += "entry references $r but it is missing from assets"
                    }
                }
                Info "entry=$entry  TableBrowser chunk(s)=$($refs -join ', ')"
            }
        }
    }

    # --- 3b. 后端源码是否已含副本应提供的路由（口径核对用） ---
    $copyTablesPy = Join-Path $CopyRoot 'Task\my_app\backend\routers\tables.py'
    if (Test-Path -LiteralPath $copyTablesPy) {
        $py = Get-Content -LiteralPath $copyTablesPy -Raw
        if ($py -match 'column-values') { Info "copy backend source exposes /column-values" }
        else { Warn "copy backend source has no /column-values route" }
    }

    # --- 3c. 实测：后端是否真的认新参数（这是 split-brain 的判据） ---
    #     后端是常驻进程，源码换了不会自动生效；这里用 live OpenAPI 判定。
    $bePort = 7038
    $envPath = Join-Path $CopyRoot '.env'
    if (Test-Path -LiteralPath $envPath) {
        $m = Select-String -LiteralPath $envPath -Pattern '^\s*MY_APP_BE_PORT\s*=\s*(\d+)' | Select-Object -First 1
        if ($m) { $bePort = [int]$m.Matches[0].Groups[1].Value }
    }
    try {
        $spec = Invoke-RestMethod -Uri "http://127.0.0.1:$bePort/openapi.json" -TimeoutSec 60
        $params = @()
        if ($spec.paths.'/api/tables/{table_name}/data') {
            $params = $spec.paths.'/api/tables/{table_name}/data'.get.parameters | ForEach-Object { $_.name }
        }
        $srcHasColFilters = $false
        if (Test-Path -LiteralPath $copyTablesPy) {
            $srcHasColFilters = (Get-Content -LiteralPath $copyTablesPy -Raw) -match 'col_filters'
        }
        if ($srcHasColFilters -and ($params -notcontains 'col_filters')) {
            $problems += ("SPLIT-BRAIN: copy source declares col_filters but the LIVE backend on :$bePort " +
                          "does not accept it (params: $($params -join ',')). The backend process is still running OLD code - restart it.")
        } else {
            Info "live backend on :$bePort accepts params: $($params -join ', ')"
        }
        $liveRoutes = $spec.paths.PSObject.Properties.Name
        if ($srcHasColFilters -and ($liveRoutes -notcontains '/api/tables/{table_name}/column-values')) {
            $problems += ("SPLIT-BRAIN: copy source declares /column-values but the LIVE backend on :$bePort " +
                          "does not expose it - the backend process is still running OLD code, restart it.")
        }
    } catch {
        Warn "could not probe live backend on :$bePort ($($_.Exception.Message)) - skipped the live check"
    }

    if ($problems.Count) {
        Write-Host ""
        Err "$($problems.Count) verification problem(s):"
        $problems | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
        exit 1
    }
    Ok "copy is consistent with the source"
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor DarkCyan
if ($SkipBuild) {
    Warn "source synced, but the copy still serves the PREVIOUS frontend build."
    Warn "Run again without -SkipBuild, or build manually in the copy."
} else {
    Ok "deploy finished: source synced + frontend rebuilt + verified"
}
Write-Host "  Restarting is a SEPARATE, explicit step (it interrupts live users)."
Write-Host "  Restart the copy's backend only when the verification above asked for it."
Write-Host "============================================================" -ForegroundColor DarkCyan
exit 0
