# 13 运维手册

## 进程与端口速查

| 端口 | 进程 | 绑定 | 谁负责活着 |
| --- | --- | --- | --- |
| `7038` | uvicorn / FastAPI | `0.0.0.0` | `backend_watchdog.py` |
| `7090` | vite preview（前端） | `0.0.0.0` | `start_hidden.ps1:244` |
| `5432` | PostgreSQL 16 | 视 `listen_addresses` | 自启脚本用 `pg_ctl` 拉起 |
| `8787`/`8790` | 实时代理（FMS / VMAX） | **仅 `127.0.0.1`** | backend 启动线程 |
| 无端口 | worker × 5 组（u/n/v/m/c） | — | `worker_watchdog.py` |

> ⚠️ **7038/7090 与 MTN_Comsal 项目共用**，两套不能同时运行（PROJECT_DOCS.md 局域网章节原文即如此）。端口被占时 `start_hidden.ps1` 会 FAIL 并提示先 `stop.bat` 或加 `-Force`（:166-168）。

## 日常巡检（5 分钟）

1. **任务管理页**：有没有 `failed`、有没有长期 `pending`。失败聚合视图比翻列表快。
2. **顶栏/页头同步标签**：`最近同步` 是否在预期窗口内（GIS/TTWO/Dashboard 三页有该标签）。
3. **数据总览页**：表数量与行数是否明显异常。
4. 命令行看进程与心跳：

```powershell
# 五个关键进程是否都在
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" |
  Select-Object ProcessId, CommandLine | Format-Table -Wrap

# 心跳是否新鲜（超过 3 分钟未更新会被判定 hung 并强杀重拉）
Get-ChildItem D:\01_RPA\Task\my_app\log\heartbeat_*.json |
  Select-Object Name, LastWriteTime
```

5. 数据库新鲜度巡检由 `db_freshness_check` 每小时 :15 自动做，滞后会在其执行日志里给出调用链与检查方向（`task_registry.py:311-315`）。

## 日志

| 文件（`log/`） | 内容 | 备注（2026-08-27 实测体积） |
| --- | --- | --- |
| `backend_runtime.log` | 后端业务日志 | **≈81 MB** |
| `backend_watchdog.log` | 后端拉起/退避记录 | **≈41 MB** |
| `worker_runtime*.log` | 任务执行主日志（**排障首选**）；每组 worker 一个文件：`_u`/`_n`/`_v`/`_m`/`_c` | 合计 ≈28 MB |
| `worker_watchdog.log` | worker 拉起记录 | |
| `frontend_runtime.log` | 前端 preview 输出 | |
| `*_console.log` / `*.log.err` | 各子进程 stdout/stderr（`start_hidden.ps1:80-83`） | |
| `realtime_proxy_fms_console.log`、`realtime_proxy_vmax_console.log` | 实时代理 | |
| `cm_data_sync.log` | CM 小区数据同步 | |
| `heartbeat_backend_watchdog.json`、`heartbeat_worker_watchdog.json` | 心跳时间戳 | |
| `start_hidden_result.txt` | 上一次启动的逐条结果（`start_hidden.ps1:263-268`） | **启动失败先看这个** |
| `pg_autostart.log`、`pg_ensure.log` | PG 拉起记录 | 按需生成 |

> 🔴 **没有日志轮转**：全仓库无 `RotatingFileHandler`。日志只会一直涨，需人工定期清理（下面的清理步骤）。
> ⚠️ 部分日志的报错原文里含账号，打包外发前先扫一遍。
> `backend/restart_dbg.log`（≈751 KB）是调试残留，可直接删。

## 排障 FAQ

| 现象 | 先查什么 | 处置 |
| --- | --- | --- |
| 页面打不开 | `start_hidden_result.txt` 里哪一步 FAIL | 按步骤重启；端口被占用 `start_hidden.ps1 -Force` |
| 启动即 `[FAIL] Python not found` | `start_hidden.ps1:88-103` 的探测顺序 | 装 Python 3.12 或让 `pythonw.exe` 进 PATH |
| 某类数据全停更 | 任务管理里对应任务是否 pending；`db/app.db` 里 `select * from task_queue where status='pending'` 是否只有那一条、且 `task_execution_log` 里该任务 0 条记录 | pending 且从不执行 → **该 task_id 不在 `GROUP_TASK_MAP` 任何组**（已踩四次，`04-task-system.md`）。补登记分组后需 `python restart_workers.py --mode watchdog --force`（**要管理员权限**：分组清单在 watchdog 进程内存里，只重启子 worker 不生效；无权限时 taskkill 会 Access denied 而静默失败，必须回查 `log/worker_restart_marker.log` 确认 pids 真的变了）；陈旧 pending 占住的单飞名额会在 6h 后被 `_expire_orphan_pending` 自动释放 |
| 任务漏跑但没人发现 | `db_freshness_check` 执行历史里搜 `[TASK-HEALTH]`；告警去重状态 `TMP/task_health_alert_state.json` | 2026-09-18 起漏跑（无执行记录/队列滞留/成功逾期/未归组）会微信+邮件主动通知，新异常与恢复各通知一次、持续超 24h 重提；维护窗口静音用 `TASK_HEALTH_ALERT_ENABLED=0` |
| 任务反复 failed | `worker_runtime*.log` 找该 task_id 堆栈（分组日志，可按任务所属组直接定位） | 上游不可达→先跑"系统设置→凭据→测试连接"；口令变了→更新凭据 |
| 任务卡在"执行中"很久 | 是否真在跑：看 worker 进程 PID 是否存活 | 无需手工干预：`STALE_RUNNING_SECONDS=30min` + PID 核对会自动回收僵尸（`worker.py:78,82,302`） |
| 邮件没发出去 | `email_recovery`（每 20 分钟）日志 | EWS 恢复后会自动补发；确认收件人配置未被重置 |
| PG 连不上 / 启动 WARN | `start_hidden.ps1:137` 的 PG 探活结果 | 管理员运行 `stop.bat all` 再 `start.bat`；仍不行手工 `pg_ctl start` |
| 只有某个看板数字不对 | 该看板的数据源任务与新鲜度开关 | 例：电池看板默认只统计 ≤24h 新鲜数据（`11-feature-guide.md` 第 13 节），不是 bug |
| 反复被重启 | `backend_watchdog.log` 连崩计数 | 连崩 10 次会放弃并告警（`backend_watchdog.py:38-44`），必须看崩溃原因，重启不解决问题 |
| 界面英文环境出现中文 | 该文案是否 zh/en 两处都加（`i18n.tsx`） | 补 en 侧同名 key。历史上出现过两次同类缺陷 |
| 启动报"已有实例" | `db/instance.lock` 是否残留（上次异常退出） | 确认无 backend 进程后删除该锁文件再启 |
| 中文注释变成乱码（`?`/`\ufffd`） | 是否用过 PowerShell `Get-Content -Raw \| Set-Content` 往返改写源文件 | **这是已知会毁 UTF-8 中文的操作，禁止用它改本仓源码**（`write`/`edit` 工具或 Python 均可）。自检：`python TMP\_check_encoding_clean.py`，会列出含替换字符与可疑 `??` 的行；恢复手段是 `git checkout -- <文件>` 取回干净版本后重施改动 |
| 某看板**单个指标**从某天起没了（其它指标正常） | `daily_kpi` 里那天的 `blocks_ok` 是否小于块总数 | 见下条「KPI 残缺日」 |
| VMAX 90 天看板某指标断档 / 页面 Build 时间不动 | `data/olib_soc_report/olib_soc_report.sqlite3` 的 `daily_kpi` 表 | 见下方专节 |
| 门户点开看板看到「需要登录：请先通过统一门户登录后再访问看板数据」 | 该浏览器的门户登录态是否有效（`localStorage` 的 `liberia_noc_auth_v1`） | **不一定是看板坏了**。my_app 认可三种身份来源：URL 深链 `?t=`、门户登录态、myapp 自身会话。目录里那串 `&t=` 是**门户会话 token**，而门户会话是**纯内存 + 12h 滑动过期、服务重启即清空**（门户 `server/auth/store.ts:32`），所以它**会过期**，目录里 21 条共用同一串、过期后一起失效 —— 这是常态而非本次改动引入。本机自测常看不出来，因为门户后端对 `localhost`/`127.0.0.1` 自动放行（`api.ts:474-485` 的换会话逻辑）。判据：让该用户重新登录门户再点。端到端回归：`python TMP\_verify_portal_card_click.py` |
| 门户里少了 / 多了某张看板卡 | `backend\data\portal_catalog.json`（服务端全局目录，**53~54 条**） | 门户的看板清单**不在静态 assets 里**，而在服务端目录：`GET/PUT /api/portal-catalog`（`backend\routers\portal_catalog.py`，落盘 `backend\data\portal_catalog.json`，整体原子替换写）。改它请走接口而不是手改 JSON —— `_normalize_item`（`:205-257`）会校验 `titleZh/titleEn` 至少一个非空、`url` 必须以 `http(s)://` 开头，手改漏字段会让整份目录被丢掉。`no` 是分组成员覆盖与卡片锚点的键，**取当前最大号 +1，不复用已删编号**。回归：`python TMP\_verify_portal_ttwo_split.py` |

### KPI 残缺日的识别与修复（2026-09-24 事故）

现象：`?page=vmaxCxoDashboard_90Days` 的「Active Users」停在某天之前，之后全是空，
但流量/视频等其它指标正常。**页面上的 `Build MM-DD HH:MM` 是页面文件自身的修改时间，
不是数据时间**，所以它不动是正常的 —— 数据时间看左侧「数据截至」与状态栏。

根因：单日取数时某个块临时失败，那一行仍被写入（其余块有值），只是该块对应的列为 NULL。
这种「行在但格子空」的天既不算任务失败、也不算缺天，于是**永久残留**。

```sql
-- 一行定位：blocks_ok 小于 7 的日期就是残缺日（看板共 7 个块）
SELECT day, blocks_ok, traffic_tb, active_user, video_tb
FROM daily_kpi ORDER BY day DESC LIMIT 15;
```

修复（幂等，重取即自愈；2026-09-24 起每日任务已自动覆盖这类天）：

```bash
python -m backend.services.olib_soc_report.olib_soc_report_service --sync-kpi --days-back 30
```

> 判定逻辑在 `olib_soc_kpi_store.incomplete_days()`（列白名单 `REQUIRED_COLUMNS`），
> 与 `gap_days()` 一起决定每天要补哪些天。改库前先备份该 sqlite 文件。

## 备份与恢复

**三处都要备，缺一不完整**（原因见 `03-data-layer.md`、`05-security-and-credentials.md`）：

| 对象 | 内容 | 方式 |
| --- | --- | --- |
| 远程 PostgreSQL | 主业务库 + `task_queue`/`task_execution_log`/`task_schedule_config` | `pg_dump`；`pg_to_sqlite_sync` 每小时 :45 已提供一份镜像到 `db/app.db` |
| `db/app.db` | **凭据表 `credentials`（明文）** + PG 快照镜像 | 直接复制文件（含口令，按敏感介质保管） |
| `data/` + `backend/data/` | 各任务报表产物、`settings.json` | 复制目录。丢 `settings.json` 会退回内置默认远程主机 |
| `backend/services/*.json` | 上游连接参数与 TT 规则表 | 这些属于代码资产，随仓库走 |

恢复顺序：起 PG → 还原库 → 放回 `db/app.db` → 放回 `data/` → `start.bat` → 任务管理手动跑一个轻任务验证。

## 局域网访问

其他电脑访问本机部署，需要放行三组端口：`7090`（前端）、`7038`（后端）、`5432`（PG，仅当别人的 my_app 要连你的库）。

1. **确认本机 IP**：`ipconfig | findstr /i "IPv4"`。DHCP 下 IP 会变，变了要同步改各电脑 `.env`。
2. **访问地址**：`http://<本机IP>:7090/myapp/`。后端与 preview 都已绑 `0.0.0.0`（`backend_watchdog.py:149`、`vite.config.ts:9-10`）。
3. **让别人的 my_app 连你的 PG**：需改 `pg_hba.conf` 加 `scram-sha-256` 规则 + 重载配置 + 防火墙放行 TCP 5432；对方 `backend/.env` 里 `DATABASE_URL` 指向你的 IP，`MY_APP_DB_MODE=pg`。
4. **CORS**：非同源访问需把来源加进 `MY_APP_CORS_ORIGINS`。

> ⚠️ **文档与现实不符之处（已实测）**：PROJECT_DOCS.md 原文提到用 `firewall_setup.bat`、`setup_pg_lan_access.bat`、`install_ensure_task.bat` 三个脚本自动完成上述步骤，但：
> - `firewall_setup.bat` — **本项目内不存在**；同机 `D:\01_RPA\Task\MTN_Comsal\my_app\firewall_setup.bat` 有一份同名脚本，可参考，但端口与路径按那个项目写的，**不能直接拿来跑**。
> - `setup_pg_lan_access.bat`、`install_ensure_task.bat` — **`D:\01_RPA` 全树均未找到**。
>
> 结论：第 3 步（PG 局域网放行）与防火墙规则都得手工做。这是待补的脚本缺口，不是手册写错。补脚本时请遵守本文末尾的 bat 规范（CRLF + 英文 `REM`）。
>
> 另：暴露到局域网即等于把系统交给全网（**没有账号体系**，且反向代理下 Token 校验失效）。放开前读 `05-security-and-credentials.md`。

## 开机自启

```
计划任务(每5分钟) → start_ensure.bat → start_hidden.ps1 -Quiet -Force
HKCU\...\Run      → start_hidden.vbs → start_hidden.ps1 -Quiet
```

- `-Quiet` 会**尊重 `stopped.flag`**：手工 `stop.bat` 后不会被自启拉起（`start_hidden.ps1:125`）。想恢复自动启动就跑 `start.bat`（开头清标记，`start.bat:13`）。
- 自启脚本硬编码了 `C:\Program Files\PostgreSQL\16\*` 与当前用户目录下的 Python 路径（`start_autostart.bat:14,25`、`start_ensure.bat:15,20`、`stop.bat:25,100`）。换用户/换机必须改。
- **改 `.bat` 后必须实跑一次并用 PID 前后对比验证**——本项目吃过亏：cmd 把 UTF-8 无 BOM 的中文注释按 ANSI 解析会吞掉后续行，脚本照样显示成功但 `taskkill` 根本没执行。所有 bat 保持 CRLF + 英文 `REM`（`start.bat:21-22`）。

## 定期清理

| 目标 | 位置 | 安全性 |
| --- | --- | --- |
| 运行日志 | `log/*.log`（大文件先停服务再清，避免句柄占用） | 安全，历史问题就查不回来了 |
| 队列与执行日志 | 主库 `task_queue`、`task_execution_log` | **系统自动保留 3 天**（`task_runner.py:764`、`worker.py:240`），无需手工 |
| 一次性调试产物 | `log/edge_cleanup*.txt`、`killlog*.txt`、`pidcheck.txt`、`identify.txt`、`backend/restart_dbg.log`、根目录 `send_test_v22.log` | 安全 |
| 历史空库 | `data/app.db`、`data/my_app.db`（均 0 字节） | 安全 |
| 旧构建目录 | `frontend/dist`、`dist2`、`dist3`（未被 `outDir` 使用） | 删前确认 nginx 没指向它们 |

**不要动**：`db/app.db`（含凭据 + 快照）、`backend/services/auth_cache/`（有效登录态）、`data/` 下各任务目录、根目录 `eflow_TT_rules.xlsx`（是副本但可能是你手工维护的规则源）。

`monitor_fixes/` 是监控远程主机（DB 写入 API 8765 / FTP 21 / nginx 80）的修复版 PowerShell 脚本集，路径为 `E:\01_RPA\...`，与本机启停无关，**别拿它当启停脚本**。

## 测试

`tests/` 是 API + Playwright E2E 套件，用法与报告位置见 `tests/README_tests.md`，报告落 `tests/reports/`。改完代码建议至少跑一遍受影响的 API 测试。
