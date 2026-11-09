<#
  write_nginx_conf.ps1 —— 按副本实际所在盘符/端口展开 nginx 配置
  =============================================================================
  为什么需要这一步：nginx 的 alias/root 必须是绝对路径，而副本拷到别的电脑后
  盘符与目录名都会变（D:\01_olbr_portal → E:\xxx → C:\Users\me\olbr）。
  所以仓库里存的是带 {{ROOT}} 占位符的 nginx.conf.template，**每次启动时**
  按 $PSScriptRoot 推出真实根目录再展开，配置里不写死任何盘符。

  输出编码必须是「UTF-8 无 BOM」：nginx 把 BOM 当成首个 directive 的一部分，
  会直接 [emerg] unknown directive。而 Windows PowerShell 5.1 的
  Set-Content -Encoding UTF8 **会加 BOM**，所以这里用 .NET 的 UTF8Encoding($false)。

  用法（一般由 start_all.ps1 调用，也可单独跑）：
    powershell -NoProfile -File write_nginx_conf.ps1
    powershell -NoProfile -File write_nginx_conf.ps1 -HttpPort 8080 -BePort 17038
  =============================================================================
#>
[CmdletBinding()]
param(
    [string]$Root = '',
    [int]$HttpPort = 0,
    [int]$BePort = 0,
    [int]$FePort = 0,
    [int]$PortalPort = 0,
    [switch]$SkipValidate
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$sw = [System.Diagnostics.Stopwatch]::StartNew()

# 本脚本被铺在副本根目录，所以根 = 脚本所在目录
if (-not $Root) { $Root = $PSScriptRoot }
$Root = (Resolve-Path -LiteralPath $Root).Path
# nginx 在 Windows 上接受正斜杠；反斜杠在 conf 里是转义字符，必须换掉
$rootFwd = $Root.Replace('\', '/').TrimEnd('/')

# 端口：显式参数 > 环境变量 > 生产默认值
function Resolve-Port {
    param([int]$Explicit, [string]$EnvName, [int]$Default)
    if ($Explicit -gt 0) { return $Explicit }
    $v = [Environment]::GetEnvironmentVariable($EnvName, 'Process')
    if ($v -and $v -match '^\d+$') { return [int]$v }
    return $Default
}
$HttpPort   = Resolve-Port $HttpPort   'NGINX_HTTP_PORT' 80
$BePort     = Resolve-Port $BePort     'MY_APP_BE_PORT'   7038
$FePort     = Resolve-Port $FePort     'MY_APP_FE_PORT'   7090
$PortalPort = Resolve-Port $PortalPort 'PORTAL_PORT'      9267

$nginxDir = Join-Path $Root 'nginx-1.28.0'
$tplPath  = Join-Path $Root 'nginx.conf.template'
$confDir  = Join-Path $nginxDir 'conf'
$confPath = Join-Path $confDir 'nginx.conf'

if (-not (Test-Path -LiteralPath $tplPath)) { throw "缺少模板: $tplPath（请先跑主仓库 scripts\build_olbr_portable.ps1 -Stage config）" }
if (-not (Test-Path -LiteralPath (Join-Path $nginxDir 'nginx.exe'))) { throw "缺少 nginx.exe: $nginxDir（请先跑 -Stage nginx）" }

# 读模板必须显式 UTF8：PS 5.1 默认按 ANSI 读，中文注释会变乱码
$text = [System.IO.File]::ReadAllText($tplPath, [System.Text.Encoding]::UTF8)
$text = $text.Replace('{{ROOT}}', $rootFwd)
$text = $text.Replace('{{HTTP_PORT}}', [string]$HttpPort)
$text = $text.Replace('{{BE_PORT}}', [string]$BePort)
$text = $text.Replace('{{FE_PORT}}', [string]$FePort)
$text = $text.Replace('{{PORTAL_PORT}}', [string]$PortalPort)

if ($text -match '\{\{[A-Z_]+\}\}') { throw "模板里还有未替换的占位符: $($Matches[0])" }

# nginx 启动前必须能写 logs/ 与 temp/，否则 error_log 打不开直接退出
foreach ($d in @('conf', 'logs', 'temp')) {
    $p = Join-Path $nginxDir $d
    if (-not (Test-Path -LiteralPath $p)) { New-Item -ItemType Directory -Path $p -Force | Out-Null }
}

$utf8NoBom = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText($confPath, $text, $utf8NoBom)
Write-Host "[nginx-conf] 已生成 $confPath"
Write-Host ("[nginx-conf] ROOT={0}  HTTP={1}  BE={2}  FE={3}  PORTAL={4}" -f $rootFwd, $HttpPort, $BePort, $FePort, $PortalPort)

if (-not $SkipValidate) {
    # -t 只验语法不启动。必须带 -p 指到副本自己的 nginx 目录，
    # 否则相对路径（html / logs / include mime.types）会解析到别处。
    $exe = Join-Path $nginxDir 'nginx.exe'
    & $exe -t -p "$nginxDir\" -c 'conf/nginx.conf' 2>&1 | ForEach-Object { Write-Host "  $_" }
    if ($LASTEXITCODE -ne 0) { throw "nginx 配置语法校验失败（exit=$LASTEXITCODE），未启动" }
    Write-Host '[nginx-conf] 语法校验通过'
}

$sw.Stop()
Write-Host ("[nginx-conf] 耗时 {0:N1} 秒" -f $sw.Elapsed.TotalSeconds)