# =============================================================================
# sync-runtime-config-to-02.ps1 —— 把 D:\01_olbr_portal 的「全局 UI 配置」同步到 D:\02_olbr_portal
# -----------------------------------------------------------------------------
# 背景：D:\01_olbr_portal（80/443）与 D:\02_olbr_portal（隔离端口 8080/8443）是同一仓库的两个
#       检出，且 02 的 backend 是重构后的域分包布局 —— 代码**不能**整目录 robocopy 覆盖。
#       但「全局 UI 配置」是运行时 JSON，my_app 后端每次请求都现读文件（routers\ui_tool_order.py
#       的 _read_visibility/_read_order 无缓存），复制过去即对所有人生效，**无需重启**。
#
# 白名单（只同步这几份，其余一律不碰）：
#   backend\data\ui_tool_visibility.json   eflow_qa 页 6 个工具块的全局隐藏配置
#   backend\data\ui_tool_order.json        eflow_qa 页工具块的全局默认顺序
#   backend\data\ui_menu_layout.json       my_app 侧栏目录（分组/顺序/隐藏）全局布局
#
# 刻意**不在**白名单里（02 有自己的实例状态，同步会砸坏）：
#   .env（端口不同）、db\（本地权威表 credentials/task_schedule_config/email_recipients）、
#   log\、TMP\、auth_cache\、portal-default.json、portal auth-data\、nginx conf（02 按 .env 生成）。
#
# 代码/页面级的改动不要用本脚本：走 git（01 的 master 推 GitHub，02 里 fetch + merge）。
#
# 用法：
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\sync-runtime-config-to-02.ps1          # 试运行
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\sync-runtime-config-to-02.ps1 -Apply   # 实际复制
# =============================================================================
param([switch]$Apply)

$ErrorActionPreference = 'Stop'

$SrcRoot = 'D:\01_olbr_portal\Task\my_app\backend\data'
$DstRoot = 'D:\02_olbr_portal\apps\my_app\backend\data'
$Files   = @('ui_tool_visibility.json', 'ui_tool_order.json', 'ui_menu_layout.json')

if (-not (Test-Path $SrcRoot)) { throw "源目录不存在: $SrcRoot" }
if (-not (Test-Path $DstRoot)) { throw "目标目录不存在: $DstRoot（02 副本未就位？）" }

function Get-Md5($path) {
    if (-not (Test-Path $path)) { return $null }
    (Get-FileHash $path -Algorithm MD5).Hash
}

$copied = 0; $same = 0; $missing = 0
foreach ($f in $Files) {
    $src = Join-Path $SrcRoot $f
    $dst = Join-Path $DstRoot $f
    if (-not (Test-Path $src)) { Write-Host "[跳过] 源不存在: $f"; $missing++; continue }

    $h1 = Get-Md5 $src; $h2 = Get-Md5 $dst
    if ($h1 -eq $h2) { Write-Host "[一致] $f"; $same++; continue }

    if (-not $h2) { Write-Host "[新增] $f  （02 上还没有这份配置）" }
    else {
        Write-Host "[差异] $f"
        Write-Host "   01: $((Get-Content $src -Raw).Trim())"
        Write-Host "   02: $((Get-Content $dst -Raw).Trim())"
    }
    if ($Apply) {
        Copy-Item $src $dst -Force
        if ((Get-Md5 $dst) -ne $h1) { throw "复制后校验失败: $dst" }
        Write-Host "   -> 已复制并校验一致（后端现读文件，立即生效，无需重启）"
        $copied++
    }
}

Write-Host ''
if ($Apply) {
    Write-Host "完成：复制 $copied 份，本就一致 $same 份，源缺失 $missing 份。"
} else {
    Write-Host "以上是试运行结果（未写入）。确认无误后加 -Apply 实际执行："
    Write-Host "  powershell -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Apply"
}
