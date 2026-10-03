# =============================================================================
# pg_migrate.ps1 —— 把 my_app 的 PostgreSQL 库从一台机器搬到另一台
# =============================================================================
# 为什么需要这个脚本
# -----------------------------------------------------------------------------
# my_app 的真实数据**不在** `db\app.db`（那 1.5GB SQLite 在 pg 模式下根本没被读），
# 而在 PostgreSQL 里。实测（2026-10-03）：
#   · backend\.env  : MY_APP_DB_MODE=pg
#   · /api/health   : {"db_mode":"pg","database":"postgresql"}
#   · 库 myapp      : 2183 MB / 97 张表 / 约 310 万行
#   · 表**不在 public**，search_path 是
#       app, eflow, lte_pl, battery, ms_sla, fw, ipran_ume, ran_ume, public
#     —— 只 dump public 会得到一个"成功但空"的备份，这是本脚本要防的头号事故。
#
# 且 alembic 迁移**只建表结构、零 INSERT**（5 个迁移里只有 CREATE INDEX），
# 所以没有任何 seed 能从仓库重建数据，只能物理搬迁。
#
# 用法
# -----------------------------------------------------------------------------
#   # 在【源机器】上导出（2183MB 的库 → 实测压缩后 81.8MB，约 19 秒）
#   .\pg_migrate.ps1 dump    -Out D:\myapp.dump
#
#   # 在新机器上导入（先确保 PostgreSQL 已装好、目标库已存在）
#   .\pg_migrate.ps1 restore -In  D:\myapp.dump
#
#   # 新机器上库还不存在时，建库需要超级用户（业务账号没有建库权限，见下）
#   .\pg_migrate.ps1 restore -In D:\myapp.dump -SuperUser postgres
#
#   # 只看会执行什么、不实际执行
#   .\pg_migrate.ps1 dump -Out D:\myapp.dump -WhatIf
#
# 参数默认值从 backend\.env 的 DATABASE_URL 读取（含口令），
# **不会**把口令打印到屏幕或写进日志。
#
# 新机器的前置条件（否则 restore 会在第一步失败）
# -----------------------------------------------------------------------------
#   1. 已安装同版本 PostgreSQL（实测环境是 16）
#   2. 已创建业务角色与数据库（**这一步不能用业务账号自己做** ——
#      实测 myapp 的 rolcreatedb=f / rolsuper=f，没有建库权限）：
#        psql -U postgres -c "create role myapp login password '<口令>'"
#        psql -U postgres -c "create database myapp owner myapp"
#      ⚠ 库的 owner 必须是业务账号，否则恢复后应用连不上或无权建表。
#   3. backend\.env 里的 DATABASE_URL 指向新库
#
#   备份文件里已含全部 11 个 schema（app/eflow/lte_pl/...），
#   恢复后应用才拿得到数据 —— 这也是"只备份 public 会得到一个成功但空的备份"
#   这个头号事故的防点。
# =============================================================================
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('dump', 'restore')]
    [string]$Action,

    [string]$Out,
    [string]$In,

    # restore 时用于「建库」这一步的超级用户。
    # ⚠ 不能复用 DATABASE_URL 里的业务账号：实测 myapp 的 rolcreatedb=f / rolsuper=f，
    #   建库会报「创建数据库权限不够」。建库用超级用户、**恢复数据仍用业务账号**。
    # 该账号的口令通过 PGPASSWORD 环境变量传入（见 $SuperUserPassword 说明），不写进命令行。
    [string]$SuperUser,
    [securestring]$SuperUserPassword,

    [string]$PgBin = 'C:\Program Files\PostgreSQL\16\bin',
    [switch]$WhatIf
)

$ErrorActionPreference = 'Stop'

$myApp = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $myApp 'backend\.env'

# ---------- 从 .env 读 DATABASE_URL（不打印口令） ----------
function Get-DbUrl {
    if (-not (Test-Path $envFile)) {
        throw "找不到 backend\.env —— 新机器上请先从原机器拷贝它（含凭据，不入库）"
    }
    foreach ($line in Get-Content $envFile -Encoding UTF8) {
        $t = $line.Trim()
        if ($t -match '^DATABASE_URL\s*=\s*(.+)$') { return $Matches[1].Trim() }
    }
    throw "backend\.env 里没有 DATABASE_URL"
}

# 解析 postgresql://user:pass@host:port/dbname
function Parse-DbUrl([string]$url) {
    if ($url -notmatch '^postgres(ql)?://(?<user>[^:@/]+):(?<pass>[^@]*)@(?<host>[^:/]+):?(?<port>\d+)?/(?<db>[^?]+)') {
        throw "DATABASE_URL 格式无法解析（期望 postgresql://user:pass@host:port/db）"
    }
    return @{
        User = $Matches['user']; Pass = $Matches['pass']
        Host = $Matches['host']; Port = if ($Matches['port']) { $Matches['port'] } else { '5432' }
        Db   = $Matches['db']
    }
}

function Get-Tool([string]$name) {
    $p = Join-Path $PgBin "$name.exe"
    if (-not (Test-Path $p)) {
        throw "找不到 $p —— 请用 -PgBin 指定 PostgreSQL 的 bin 目录"
    }
    return $p
}

# ---------- 主流程 ----------
$url = Get-DbUrl
$db = Parse-DbUrl $url

Write-Host "=" * 70
Write-Host " my_app PostgreSQL 迁移 —— 动作: $Action"
Write-Host " 目标库: $($db.Host):$($db.Port)/$($db.Db)  用户: $($db.User)"
Write-Host "=" * 70

# 口令通过环境变量传给 pg 工具，避免出现在命令行（进程列表可见）与日志里
$env:PGPASSWORD = $db.Pass

try {
    if ($Action -eq 'dump') {
        if (-not $Out) { throw "dump 需要 -Out <文件路径>" }
        $pgDump = Get-Tool 'pg_dump'

        Write-Host "[1/2] 先列出将要备份的 schema（防 public-only 空备份）..."
        $psql = Get-Tool 'psql'
        $schemas = & $psql -h $db.Host -p $db.Port -U $db.User -d $db.Db -At `
            -c "select nspname from pg_namespace where nspname not like 'pg_%' and nspname <> 'information_schema' order by 1"
        Write-Host "      schema: $($schemas -join ', ')"

        Write-Host "[2/2] pg_dump（自定义格式，已压缩）..."
        # -F c 自定义格式：支持 pg_restore 并行/选择性恢复，且自带压缩
        # 不加 -n：**必须 dump 全部非系统 schema**，否则会得到"成功但空"的备份
        $args = @('-h', $db.Host, '-p', $db.Port, '-U', $db.User, '-d', $db.Db,
                  '-F', 'c', '-f', $Out)
        if ($WhatIf) {
            Write-Host "      [WhatIf] & `"$pgDump`" $($args -join ' ')"
        } else {
            & $pgDump @args
            if ($LASTEXITCODE -ne 0) { throw "pg_dump 失败（退出码 $LASTEXITCODE）" }
            $size = [math]::Round((Get-Item $Out).Length / 1MB, 1)
            Write-Host "      OK → $Out ($size MB)"
        }
        Write-Host ""
        Write-Host "把 $Out 拷到新机器，然后在那里执行："
        Write-Host "  .\pg_migrate.ps1 restore -In <该文件的路径>"
    }
    else {
        if (-not $In) { throw "restore 需要 -In <文件路径>" }
        if (-not (Test-Path $In)) { throw "找不到备份文件: $In" }
        $pgRestore = Get-Tool 'pg_restore'
        $createdb = Get-Tool 'createdb'
        $psql = Get-Tool 'psql'

        Write-Host "[1/4] 确保目标库存在..."
        # ⚠ 2026-10-03 实测：业务账号 myapp 的角色属性是 rolcreatedb=f / rolsuper=f，
        #   **没有建库权限**，`createdb -U myapp` 直接报「创建数据库权限不够」。
        #   所以建库这一步必须用一个有权限的角色（通常是 postgres 超级用户），
        #   而**数据恢复仍用业务账号**（它对自己的库有全部权限）。
        #   下面先检测业务账号能否建库；不能则提示用 -SuperUser 重跑，
        #   而不是让它抛一个看不懂的权限错误。
        $exists = & $psql -h $db.Host -p $db.Port -U $db.User -d postgres -At `
            -c "select 1 from pg_database where datname='$($db.Db)'" 2>$null
        if ($exists -eq '1') {
            Write-Host "      库已存在（将直接恢复数据）"
        }
        else {
            # 决定用哪个账号建库：优先 -SuperUser，否则退回业务账号（可能没权限）
            $createUser = $db.User
            if ($SuperUser) { $createUser = $SuperUser }
            $canCreate = (& $psql -h $db.Host -p $db.Port -U $db.User -d postgres -At `
                -c "select rolcreatedb from pg_roles where rolname='$($db.User)'" 2>$null)

            if (-not $SuperUser -and $canCreate -ne 't') {
                Write-Host "      [注意] 账号 $($db.User) 没有建库权限（rolcreatedb=f），需要超级用户先建库。"
                Write-Host "             请用 -SuperUser 指定有权限的账号重跑，例如："
                Write-Host "               .\pg_migrate.ps1 restore -In <备份> -SuperUser postgres"
                throw "目标库 $($db.Db) 不存在，且 $($db.User) 无权创建它"
            }

            if ($WhatIf) { Write-Host "      [WhatIf] createdb -U $createUser $($db.Db)" }
            else {
                # 建库用超级用户口令（若提供），否则沿用业务账号口令
                $savedPwd = $env:PGPASSWORD
                if ($SuperUser -and $SuperUserPassword) {
                    $env:PGPASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
                        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SuperUserPassword))
                }
                try {
                    & $createdb -h $db.Host -p $db.Port -U $createUser $($db.Db)
                    if ($LASTEXITCODE -ne 0) { throw "createdb 失败（账号 $createUser）" }
                    Write-Host "      已创建库 $($db.Db)（用账号 $createUser）"
                }
                finally { $env:PGPASSWORD = $savedPwd }
            }
        }

        Write-Host "[2/4] 恢复 schema 与数据（--no-owner --no-privileges，便于跨机器）..."
        # --no-owner / --no-privileges：源机器与目标机器的角色名往往不同，
        #   不加会一路报 "role xxx does not exist" 但仍返回 0，容易误判成功。
        # 不写 --clean：新机器是空库，且 --clean 会先删表，误跑在有数据的库上代价大。
        # --exit-on-error：默认 pg_restore 遇到错误会继续跑完并返回非 0，
        #   中途失败与"全部成功"难以区分；这里要求遇错即停，让失败显式化。
        $args = @('-h', $db.Host, '-p', $db.Port, '-U', $db.User, '-d', $db.Db,
                  '--no-owner', '--no-privileges', '--exit-on-error', $In)
        if ($WhatIf) {
            Write-Host "      [WhatIf] & `"$pgRestore`" $($args -join ' ')"
        } else {
            & $pgRestore @args
            # pg_restore 对"已存在对象"等非致命情况也返回非 0，不能一律当失败；
            # 真正的判据是最后一步的行数核对。
            Write-Host "      pg_restore 退出码: $LASTEXITCODE（非 0 也可能只是对象已存在的警告）"
        }

        Write-Host "[3/4] 核对结果..."
        $sql = @"
select schemaname, count(*) as tables, coalesce(sum(n_live_tup),0) as rows
from pg_stat_user_tables group by schemaname order by 1;
"@
        if ($WhatIf) { Write-Host "      [WhatIf] 汇总各 schema 的表数与行数" }
        else {
            & $psql -h $db.Host -p $db.Port -U $db.User -d $db.Db -c $sql
            Write-Host "      参考基线（源机器 2026-10-03）：97 张表 / 约 3,108,259 行"
        }
        Write-Host ""
        Write-Host "[4/4] 恢复后请跑一次自检确认："
        Write-Host "  python Task\my_app\scripts\clone_doctor.py"
    }
}
finally {
    # 无论成败都清掉环境里的口令，避免残留在后续命令的进程环境里
    Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue
}
