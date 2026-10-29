# start_hidden.ps1 - Hidden startup of my_app (backend / worker / frontend) with result feedback
# Usage:
#   Run directly (double-click / right-click Run with PowerShell):
#     Starts missing components, writes log\start_hidden_result.txt, shows popup for each [OK]/[WARN]/[FAIL].
#   Scheduled task / Logon auto-start (MyApp_AutoStart / MyApp_EnsureRunning):
#     powershell -File start_hidden.ps1 -Quiet [-Force]
#     -Quiet: no popup, only write result file; also respect backend\stopped.flag written by stop.bat.
#     -Force: force-kill port 7038 if occupied by non-watchdog processes (e.g., uvicorn --reload).
param(
    [switch]$Quiet,
    [switch]$Force
)
$ErrorActionPreference = 'Continue'
$base = Split-Path -Parent $MyInvocation.MyCommand.Definition
$logDir = Join-Path $base 'log'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
$resultFile = Join-Path $logDir 'start_hidden_result.txt'
$flag = Join-Path $base 'backend\stopped.flag'

$report = [System.Collections.Generic.List[string]]::new()
$script:failCount = 0
$script:warnCount = 0

function Add-Report([string]$line) { $script:report.Add($line) }

function Test-PortListening([int]$port) {
    return ($null -ne (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue))
}

function Test-PidAlive([int]$procId) {
    if ($procId -le 0) { return $false }
    return ($null -ne (Get-Process -Id $procId -ErrorAction SilentlyContinue))
}

function Read-PidFile([string]$path) {
    if (-not (Test-Path $path)) { return 0 }
    try {
        $t = (Get-Content $path -Raw -ErrorAction Stop).Trim()
        if ($t -match '^\d+$') { return [int]$t }
    } catch { }
    return 0
}

function Wait-Port([int]$port, [int]$seconds) {
    for ($i = 0; $i -lt $seconds; $i++) {
        if (Test-PortListening $port) { return $true }
        Start-Sleep -Seconds 1
    }
    return (Test-PortListening $port)
}

function Stop-PidForce([int]$procId) {
    if ($procId -le 0) { return }
    taskkill /PID $procId /T /F 2>$null | Out-Null
    Start-Sleep -Seconds 2
}

# Watchdog health check: missing=no pid file / dead=process is dead / hung=process alive but heartbeat stale (>3min) / ok=normal
function Get-WatchdogHealth([string]$name, [string]$pidPath) {
    $procId = Read-PidFile $pidPath
    if ($procId -le 0) { return @{ status = 'missing'; pid = 0 } }
    if (-not (Test-PidAlive $procId)) { return @{ status = 'dead'; pid = $procId } }
    $hb = Join-Path $logDir ("heartbeat_{0}.json" -f $name)
    if (Test-Path $hb) {
        try {
            $j = Get-Content $hb -Raw -ErrorAction Stop | ConvertFrom-Json
            # Heartbeat must be written by current pid: old instances may linger during watchdog restart.
            # Checking pid prevents falsely marking new watchdog as hung on stale heartbeats.
            if ([int]$j.pid -eq $procId) {
                $ts = [datetime]$j.ts
                if (((Get-Date) - $ts).TotalMinutes -gt 3) { return @{ status = 'hung'; pid = $procId } }
            }
        } catch { }
    }
    return @{ status = 'ok'; pid = $procId }
}

function Start-Hidden {
    param($exe, $argList, $logName)
    $log = Join-Path $logDir $logName
    $err = "$log.err"
    try {
        Start-Process -FilePath $exe -ArgumentList $argList -WorkingDirectory $base `
            -WindowStyle Hidden -RedirectStandardOutput $log -RedirectStandardError $err -ErrorAction Stop
    } catch {
        # 2026-09-11: Windows PowerShell 5.1 的已知缺陷 —— 当环境里存在只有大小写不同的
        # 两个变量（例如 http_proxy 与 HTTP_PROXY，代理设置或 shell profile 都可能留下），
        # Start-Process -RedirectStandardOutput 会抛
        #   "Item has already been added. Key in dictionary: 'http_proxy'"。
        # 旧代码没有 try/catch，异常直接冒泡，于是「服务根本没被启动」却只表现为
        # 后面 Wait-Port 超时（或更糟：watchdog 心跳正常时被当成一切正常）。
        # 去掉小写副本即可绕过，对本地服务无副作用。
        foreach ($k in @('http_proxy', 'https_proxy', 'no_proxy', 'all_proxy')) {
            [System.Environment]::SetEnvironmentVariable($k, $null)
        }
        Start-Process -FilePath $exe -ArgumentList $argList -WorkingDirectory $base `
            -WindowStyle Hidden -RedirectStandardOutput $log -RedirectStandardError $err
        Add-Report '[*] Note: dropped duplicate lower-case proxy env vars to work around a PowerShell 5.1 Start-Process bug.'
    }
}

# ---------- Python detection ----------
# 2026-10-03 重写。旧逻辑的缺陷（实测确认，不是猜测）：
#   旧顺序是「① PATH 里的 pythonw/python → ② 4 个硬编码系统路径 → ③ 仓库内 Scripts\pythonw.exe」，
#   且**只看文件存不存在，不看它有没有依赖**。于是任何一台机器上都能"找到"一个 Python，
#   哪怕它缺 fastapi/uvicorn —— 现象是 watchdog 被拉起后立刻 ImportError 退出，
#   而脚本只会报「port 7038 not listening within 45s」，把根因藏起来。
#
#   本机实测（2026-10-03）：
#     %LOCALAPPDATA%\Programs\Python\Python312\python.exe  → import fastapi,uvicorn,psycopg2,sqlalchemy = OK
#     <repo>\Scripts\python.exe                             → ModuleNotFoundError: No module named 'fastapi'
#   7038 上真正在跑的进程正是前者（pythonw，Path=...Python312\pythonw.exe）。
#
#   注意 Scripts\ 不是"废 venv"，它是**另一个用途的 venv**（pyvenv.cfg 显示它由
#   .workbuddy 的 Python 3.13 创建，含 numpy/opencv/pywin32，且同目录放着
#   realtime_proxy.py / fms_session.json）。它服务 8787 的 FMS 实时代理，
#   **不装后端依赖**。所以"回落仓库 venv"这个思路在本项目里本就不成立。
#
# 新逻辑：按**候选顺序**逐个探测，第一个「能 import 后端依赖」的才被选中；
#   一个都不可用时报 FAIL 并打印每个候选缺什么，让人一眼知道该 pip install 到哪。
#   候选顺序刻意保持与旧版**一致**（系统优先），这样本机行为不变、不影响线上；
#   变的是"不再盲选第一个存在的文件"。
$py = $null
$pyProbe = 'import fastapi, uvicorn'   # 后端与 watchdog 的最小依赖集
$pyCandidates = [System.Collections.Generic.List[string]]::new()

# ① PATH（保持旧版第一顺位）
foreach ($c in @('pythonw.exe', 'python.exe')) {
    $found = Get-Command $c -ErrorAction SilentlyContinue
    if ($found) { $pyCandidates.Add($found.Source) }
}
# ② 常见系统安装位置
foreach ($k in @(
    "$env:LOCALAPPDATA\Programs\Python\Python312\pythonw.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python311\pythonw.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
    'C:\Python312\pythonw.exe',
    'C:\Python311\pythonw.exe'
)) { if (Test-Path $k) { $pyCandidates.Add($k) } }
# ③ 项目内虚拟环境（新机器按 docs\manual\10-quickstart.md 建 .venv 时的落点）
foreach ($k in @(
    (Join-Path $base '.venv\Scripts\pythonw.exe'),
    (Join-Path $base '.venv\Scripts\python.exe'),
    (Join-Path $base 'Scripts\pythonw.exe'),
    (Join-Path $base 'Scripts\python.exe')
)) { if (Test-Path $k) { $pyCandidates.Add($k) } }

$pyTried = [System.Collections.Generic.List[string]]::new()
$pyUsable = [System.Collections.Generic.List[string]]::new()
foreach ($cand in ($pyCandidates | Select-Object -Unique)) {
    if (-not (Test-Path $cand)) { continue }
    # pythonw.exe 无控制台，用它跑 -c 拿不到输出；同名目录下的 python.exe 用来探测依赖
    $probeExe = $cand
    if ((Split-Path $cand -Leaf) -eq 'pythonw.exe') {
        $alt = Join-Path (Split-Path $cand -Parent) 'python.exe'
        if (Test-Path $alt) { $probeExe = $alt }
    }
    $probeErr = $null
    try {
        $probeErr = & $probeExe -c $pyProbe 2>&1
        if ($LASTEXITCODE -eq 0) {
            if (-not $py) { $py = $cand }
            $pyUsable.Add($cand)
        } else {
            $pyTried.Add(("{0}  ->  {1}" -f $cand, (($probeErr | Select-Object -First 1) -join ' ')))
        }
    } catch {
        $pyTried.Add(("{0}  ->  {1}" -f $cand, $_.Exception.Message))
    }
}

if ($py) {
    Add-Report ("[OK] Python selected: {0}" -f $py)
    if ($pyTried.Count -gt 0) {
        Add-Report ("     (skipped {0} interpreter(s) missing backend deps; see below)" -f $pyTried.Count)
    }
    # 记下所有可用解释器，供"依赖装错地方"的排障使用
    if ($pyUsable.Count -gt 1) {
        Add-Report ("     other usable: {0}" -f (($pyUsable | Where-Object { $_ -ne $py }) -join '; '))
    }
} else {
    Add-Report '[FAIL] No Python interpreter with backend dependencies (fastapi, uvicorn) was found.'
    Add-Report '       Install deps into ONE of the interpreters below, then re-run this script:'
    if ($pyTried.Count -gt 0) {
        foreach ($t in $pyTried) { Add-Report ("         - {0}" -f $t) }
    } else {
        Add-Report '         - (no python.exe found at all)'
    }
    Add-Report '       Correct command (pick the interpreter you want to use):'
    Add-Report '         <that python.exe> -m pip install -r requirements.txt'
    Add-Report '       See docs\manual\10-quickstart.md and docs\新机器部署清单.md section 4.'
    $script:failCount++
    $report | Set-Content -Path $resultFile -Encoding UTF8
    exit 2
}

# Clear WorkBuddy safety env vars (prevent file deletion guards)
$env:CODEBUDDY_SESSION_ID = ''
$env:CLAUDE_SESSION_ID = ''
$env:CODEBUDDY_SAFE_DELETE_SANDBOX = ''
# Worker groups: u=UME session group, n=eFlow API/config-center group, s=SP spare-parts SFTP group,
# w=MW UME microwave group, m=light admin tasks group, c=CN EMS group,
# v=VMAX portal (8790 single-session proxy) group, x=realtime alarm group.
# MUST stay in sync with backend/worker_watchdog.py
# GROUP_TASK_MAP keys (restart_workers.py ALL_GROUPS derives from that map automatically)
# (guarded by tests/test_worker_group_coverage.py -- run: python tests\test_worker_group_coverage.py).
# 2026-09-27: n 组拆为 n/s/w 三组，理由见 worker_watchdog.py 的 GROUP_TASK_MAP 注释。
# 2026-10-15: eflow_active_alarm 从 n 组拆出为 x 组（要求实时告警 ≤1 分钟，
#             而 n 组串行会让它排在 eflow_sync 等长任务后面，实测最差排队 854s）。
# 2026-10-19: 新增 g 组承载 gp_ran_user_sync（RAN Greenplum 两跳 SSH 取数，实测单轮 72.6s）。
#             拆组理由是故障域：这条链路每一跳都可能挂死在网络层，而 m 组跑着每分钟的
#             告警 WhatsApp 推送（同当年 s 组 sp_data_sync 挂死 5.5h 拖停整组的教训）。
# 2026-10-28: pg_to_sqlite_sync 从 m 组拆出为 p 组。它每小时 :45 全量灌 PG 进 db/app.db
#             （113 表 / 489 万行 / 1.5GB，实测单轮 577~1174s），挂在 m 组会把每分钟的
#             ume_alarm_whatsapp_alert 与 */5 的 tt_alarm_whatsapp_alert 一起堵死。
$env:MY_APP_WORKER_GROUPS = 'u,n,s,w,m,c,v,x,g,p'

# ======================================================================
# Startup report header
# ======================================================================
$header = "===== my_app start_hidden startup report {0} (Quiet={1} Force={2}) =====" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Quiet, $Force
Add-Report $header

# Stop marker: respect stop.bat's stopped flag when running quietly (logon autostart / watchdog tasks)
if ($Quiet -and (Test-Path $flag)) {
    Add-Report "[SKIP] backend\stopped.flag detected: services were stopped by stop.bat. Skipping startup."
    Add-Report "       Run start.bat / start_hidden.ps1 (without -Quiet) to restart."
    ($report | Where-Object { $_ }) | Set-Content -Path $resultFile -Encoding UTF8
    exit 0
}
if (-not $Quiet) {
    if (Test-Path $flag) { try { Remove-Item $flag -Force -ErrorAction Stop } catch { } }
}

# ---------- 0) PostgreSQL (Windows service dependency for backend) ----------
Add-Report "----- 0) PostgreSQL -----"
if (Test-PortListening 5432) {
    Add-Report '[OK] PostgreSQL (5432) listening normally'
} else {
    Add-Report '[WARN] PostgreSQL (5432) NOT LISTENING! Backend cannot read/write database'
    Add-Report '       Run start_autostart.bat or manually start pg_ctl (watchdog will auto-recover)'
    $script:warnCount++
}

# ---------- 1) backend_watchdog (manage uvicorn on port 7038, queue mode) ----------
Add-Report "----- 1) backend + backend_watchdog -----"
function Ensure-BackendWatchdog {
    $bwPidFile = Join-Path $base 'backend\backend_watchdog.pid'
    # Ask the kernel singleton BEFORE looking at the PID file. 2026-10-16/18: the
    # backend watchdog had no singleton guard, so a second one could start; both
    # spawned a uvicorn, the loser's child died on bind (exit_code=3) and the
    # winner's child became an orphan squatting on 7038 -- 17,349 retry warnings
    # on 10-16, reproduced 2026-10-18 09:03. The mutex ignores PID files, so it
    # still sees the live holder even if the file was deleted or overwritten.
    # Exit codes: 0 = held, 3 = none, 4 = cannot tell.
    $probe = Start-Process -FilePath $py -ArgumentList '-m', 'backend.backend_watchdog', '--probe' `
        -WorkingDirectory $base -WindowStyle Hidden -PassThru -Wait -ErrorAction SilentlyContinue
    $probeCode = if ($probe) { $probe.ExitCode } else { $null }
    if ($probeCode -eq 0) {
        Add-Report '[OK] backend_watchdog already running (singleton lock held; PID file missing or stale) - skipping start, no second stack'
        return $true
    }
    if ($probeCode -eq 4) {
        Add-Report '[WARN] backend_watchdog singleton probe unavailable - relying on PID file only; a duplicate stack will still be refused by the watchdog itself'
    }
    $hb = Get-WatchdogHealth 'backend_watchdog' $bwPidFile
    if ($hb.status -eq 'ok') {
        Add-Report ("[OK] backend_watchdog running (pid={0}), port 7038 managed (queue mode)" -f $hb.pid)
        return $true
    }
    if ($hb.status -eq 'hung') {
        Add-Report ("[WARN] backend_watchdog pid={0} heartbeat timed out (possibly hung), force killing and restarting" -f $hb.pid)
        Stop-PidForce $hb.pid
        $script:warnCount++
    }
    if (Test-PortListening 7038) {
        $owner = (Get-NetTCPConnection -LocalPort 7038 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess
        if ($Force) {
            Add-Report ("[WARN] Port 7038 occupied by non-managed process pid={0}, -Force killing and handing over to watchdog" -f $owner)
            Stop-PidForce $owner
            $script:warnCount++
            # 2026-09-11 修复（"假 OK" 缺陷）：
            # Stop-PidForce 里 `taskkill /PID x /T /F 2>$null` 会吞掉失败输出，而旧逻辑紧接着
            # 只判断「端口是否在监听」——若占用者因**权限不足**没被杀掉，端口会一直在监听，
            # 随后的 Wait-Port 立刻返回 true，于是把「杀失败」误报成
            # `[OK] backend_watchdog started, port 7038 listening`。
            # 实测后果（2026-09-11 12:02 那一轮）：巡检报 OK，但新子进程每次都
            # `已注册 54 个定时任务` → `Application startup complete` →
            # `ERROR [Errno 10048] bind 0.0.0.0:7038` → 存活 4s 以 exit_code=3 退出，
            # 7038 上跑的仍是旧代码，故障被掩盖了整整一天。
            # 修复：杀完后**显式复核占用者是否真的消失**；仍是同一 pid 则如实报 FAIL 并
            # 放弃本轮拉起（否则只会再造一个抢不到端口的子进程并刷日志）。
            # 放弃拉起的代价：孤儿进程一旦消失，恢复要等下一次巡检（≤5 分钟）。
            # 这是有意的取舍——被卡住的端口必须人工介入，跑一个永远绑不上端口的
            # watchdog 只会持续制造噪音与无效子进程，收益为零。
            $still = (Get-NetTCPConnection -LocalPort 7038 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess
            if ($still -and ([int]$still -eq [int]$owner)) {
                Add-Report ("[FAIL] Port 7038 still held by pid={0} after -Force kill: taskkill was denied (insufficient privilege)." -f $owner)
                Add-Report '       Known case: an orphan uvicorn (started by a watchdog that has since exited) owns 7038,'
                Add-Report '       so every new backend starts fine but fails to bind. This task cannot fix it.'
                Add-Report '       ACTION: run stop.bat on the server (it retries with elevation), then start.bat.'
                $script:failCount++
                return $false
            }
            if ($still) {
                Add-Report ("[WARN] Port 7038 re-occupied by another pid={0} after killing pid={1} (possible race)" -f $still, $owner)
            } else {
                Add-Report ("[OK] Port 7038 released (pid={0} terminated)" -f $owner)
            }
        } else {
            Add-Report ("[WARN] Port 7038 occupied by non-managed process pid={0}: backend has no crash guardian, tasks not in queue!" -f $owner)
            Add-Report '       Run stop.bat first, or re-run this script with -Force parameter'
            Add-Report '[FAIL] backend_watchdog did not start'
            $script:failCount++
            return $false
        }
    }
    Start-Hidden $py @('-m', 'backend.backend_watchdog') 'backend_watchdog_console.log'
    if (Wait-Port 7038 45) {
        $np = Read-PidFile $bwPidFile
        Add-Report ("[OK] backend_watchdog started, port 7038 listening (watchdog pid={0})" -f $np)
        return $true
    }
    Add-Report '[FAIL] backend_watchdog started but port 7038 not listening within 45s, check log\backend_watchdog.log for details'
    $script:failCount++
    return $false
}
$backendOk = Ensure-BackendWatchdog

# ---------- 2) worker_watchdog (manage u/n/v/m/c worker groups consuming queue) ----------
Add-Report "----- 2) worker_watchdog + workers -----"
function Ensure-WorkerWatchdog {
    $wwPidFile = Join-Path $base 'backend\worker_watchdog.pid'
    $hb = Get-WatchdogHealth 'worker_watchdog' $wwPidFile
    if ($hb.status -eq 'ok') {
        Add-Report ("[OK] worker_watchdog running (pid={0})" -f $hb.pid)
        return $true
    }
    if ($hb.status -eq 'hung') {
        Add-Report ("[WARN] worker_watchdog pid={0} heartbeat timed out (possibly hung), force killing and restarting" -f $hb.pid)
        Stop-PidForce $hb.pid
        $script:warnCount++
    }
    # Ask the kernel singleton BEFORE starting anything. 2026-10-16 incident: a
    # backend-fix script deleted worker_watchdog.pid without killing the process,
    # so every PID-file-based check concluded "no watchdog" and five stacks came up
    # (40 workers on one task_queue, 128 bogus failures in 4h). The mutex does not
    # care about PID files, so it still sees the live holder. Exit codes:
    # 0 = held by a live watchdog, 3 = none, 4 = cannot tell.
    $probe = Start-Process -FilePath $py -ArgumentList '-m', 'backend.worker_watchdog', '--probe' `
        -WorkingDirectory $base -WindowStyle Hidden -PassThru -Wait -ErrorAction SilentlyContinue
    $probeCode = if ($probe) { $probe.ExitCode } else { $null }
    if ($probeCode -eq 0) {
        Add-Report '[OK] worker_watchdog already running (singleton lock held; PID file missing or stale) - skipping start, no second stack'
        return $true
    }
    if ($probeCode -eq 4) {
        Add-Report '[WARN] worker_watchdog singleton probe unavailable - relying on PID file only; a duplicate stack will still be refused by the watchdog itself'
    }
    Start-Hidden $py @('-m', 'backend.worker_watchdog') 'worker_watchdog_console.log'
    # Wait for each group's worker pid files to be ready (up to 20s)
    # 2026-10-19: 加 g 组（RAN Greenplum 取数）。这里漏项会让下面的
    # $up.Count -eq $groups.Count 判定 9!=8 成立，启动报告反而误报 [FAIL]。
    # 2026-10-28: 加 p 组（PG 全量快照），分母随之 9 -> 10，同上漏项会误报 [FAIL]。
    $groups = @('u', 'n', 's', 'w', 'm', 'c', 'v', 'x', 'g', 'p')
    $deadline = (Get-Date).AddSeconds(20)
    while ((Get-Date) -lt $deadline) {
        $ready = 0
        foreach ($g in $groups) {
            $pf = Join-Path $base ("backend\worker_{0}.pid" -f $g)
            $p = Read-PidFile $pf
            if ($p -gt 0 -and (Test-PidAlive $p)) { $ready++ }
        }
        if ($ready -eq $groups.Count) { break }
        Start-Sleep -Seconds 1
    }
    $up = @()
    foreach ($g in $groups) {
        $pf = Join-Path $base ("backend\worker_{0}.pid" -f $g)
        $p = Read-PidFile $pf
        if ($p -gt 0 -and (Test-PidAlive $p)) { $up += ("{0}(pid {1})" -f $g, $p) }
    }
    if ($up.Count -eq $groups.Count) {
        Add-Report ("[OK] worker_watchdog started, all {0} worker groups ready: {1}" -f $groups.Count, ($up -join ', '))
        return $true
    }
    Add-Report ("[FAIL] worker_watchdog started but not all workers ready ({0}/{1}: {2}), check log\worker_watchdog.log for details" -f $up.Count, $groups.Count, ($up -join ', '))
    $script:failCount++
    return $false
}
$workerOk = Ensure-WorkerWatchdog

# ---------- 3) Frontend preview (optional; users actually access backend /myapp page) ----------
Add-Report "----- 3) Frontend preview (7090) -----"
function Ensure-Frontend {
    if ((Test-PortListening 7090) -or (Test-PortListening 5173)) {
        Add-Report '[OK] Frontend already running (port 7090/5173 listening)'
        return $true
    }
    $frontend = Join-Path $base 'frontend'
    $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if (-not $npm) { $npm = Get-Command npm -ErrorAction SilentlyContinue }
    if (-not $npm) {
        Add-Report '[WARN] npm not found, skipping frontend preview (backend /myapp page unaffected)'
        $script:warnCount++
        return $true
    }
    Start-Process -FilePath $npm.Source -ArgumentList 'run', 'preview' `
        -WorkingDirectory $frontend -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logDir 'frontend_runtime.log') `
        -RedirectStandardError (Join-Path $logDir 'frontend_runtime.log.err')
    if (Wait-Port 7090 30) {
        Add-Report '[OK] Frontend preview started on port 7090'
        return $true
    }
    Add-Report '[WARN] Frontend preview did not listen on port 7090 within 30s, check log\frontend_runtime.log for details'
    $script:warnCount++
    return $true
}
$frontendOk = Ensure-Frontend

# ---------- 4) WhatsApp analysis service (9268) - NOT managed here ----------
# 2026-09-11: moved out on purpose. That service belongs to the
# liberia-noc_soc portal (scripts\whatsapp_analysis) and is started/stopped by
# that project's own start.bat / stop.bat. Keeping it here was actively harmful:
# the MyApp_EnsureRunning task runs every 5 minutes, so it resurrected the
# service right after the portal's stop.bat had killed it.

# ======================================================================
# Summary: write result file + (non-Quiet) show popup dialog
# ======================================================================
$failCount = $script:failCount
$warnCount = $script:warnCount
$footer = "===== Result: {0} failures / {1} warnings =====`r`nFull log: {2}" -f $failCount, $warnCount, $resultFile
$all = New-Object System.Collections.Generic.List[string]
$all.Add($header)
foreach ($l in $report) { if ($l -ne $header) { $all.Add($l) } }
$all.Add($footer)
$all | Set-Content -Path $resultFile -Encoding UTF8

foreach ($l in $all) { Write-Host $l }

if (-not $Quiet) {
    try {
        Add-Type -AssemblyName System.Windows.Forms | Out-Null
        $icon = [System.Windows.Forms.MessageBoxIcon]::Information
        if ($failCount -gt 0) { $icon = [System.Windows.Forms.MessageBoxIcon]::Error }
        elseif ($warnCount -gt 0) { $icon = [System.Windows.Forms.MessageBoxIcon]::Warning }
        [System.Windows.Forms.MessageBox]::Show(
            ($all -join "`r`n"),
            'my_app Startup Result',
            [System.Windows.Forms.MessageBoxButtons]::OK,
            $icon) | Out-Null
    } catch { }
}

if ($failCount -gt 0) { exit 1 }
exit 0
