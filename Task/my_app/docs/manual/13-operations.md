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
| **WhatsApp 告警静默发不出去**（任务却报成功） | ① `whatsapp-kb-bot\data\notify_heartbeat.json` 的 `at` 是否超过 5 分钟或 `connected=false`；②（发图）`backend\services\data\ext_liveness.json` 的 `last_seen_at` 是否超过 5 分钟 | 见下方专节「P1 告警推送通道」与「扩展在线检查」 |
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
| `/api/gis/sites` 间歇 500（`服务器内部错误，请稍后重试` + `request_id`） | 拿 `request_id` 去 `backend_runtime_<日期>.log` 搜 `[unhandled] rid=<id>`（**必须用当天那个日志文件**，后端每次重启会换文件，见 `backend_watchdog.py:47`） | 见下方专节「GIS 500：整表重建空窗」 |

### GIS 500：整表重建空窗（2026-09-29 修复）

**现象**：`?page=gis` 偶发 `GET /api/gis/sites?time_start=…&time_end=… 500`，刷新多半又好了；
同一天里同一 URL 可能先 200、再 500。`request_id` 是唯一能定位的线索。

**定位手法**（本次就是这么找到的）：

```powershell
# 拿前端报错里的 request_id 去当天日志里搜，会带出完整堆栈与真正的那一行
Select-String -Path log\backend_runtime_20260929.log -Pattern 'rid=<你的 request_id>'
```

实测堆栈顶部落在 `gis.py` 的 `_collect_rt_alarm_stats` → `UndefinedTable: 关系 "realtime_alarm" 不存在`。

**根因**：写端把整表**先删后建**，中间有一个「表不存在」的真实窗口，恰好落进去的读请求就 500。
历史上两处都有这个问题：

- `eflow_alarm_service.py` 的 `write_alarm_sqlite` / `write_history_alarm_sqlite`：显式 `DROP TABLE` + `CREATE TABLE`；
- `_write_alarm_to_appdb`：对 `realtime_alarm` 走 `write_df(..., if_exists="replace")` ——
  pandas 的 `replace` 同样是 `drop_table()` 后再建表并逐行插入（见 `pandas.io.sql.SQLTable.create`），
  **这才是 `app.realtime_alarm` 消失的真正来源**（`gis.py` 读的正是这张表）。

触发者是定时任务：`eflow_active_alarm` **每 30 分钟**（`task_registry.py:240`）、
`eflow_history_alarm` **每 3 小时**（`:247`）各重建一次，所以故障是周期性的、且极易被当成"偶发抖动"。

**修复**（两条一起才够）：

1. **写端消除空窗**：改为「影子表灌满数据 → 原子顶替」。
   ⚠️ **关键点：顶替必须是单条语句**。`_PsycopgRaw` 是 `autocommit=True`（`database.py:324`），
   若拆成 `DROP` + `RENAME` 两次 `execute`，两次独立提交之间**仍有空窗** ——
   实测并发读方仍能观测到 78~91 次 `UndefinedTable`，等于没修。
   把两条 DDL 放进一个 `DO $$ … $$` 块后 PG 按单事务执行，实测 missing = 0。
   SQLite 无 DO 块，但同连接内两条 DDL 处于同一隐式事务，不会中途提交。
2. **读端降级**：`_collect_tt_stats` / `_collect_wo_stats` / `_collect_rt_alarm_stats` /
   `_collect_his_alarm_stats` 统一走 `_run_stats_query()`，表瞬时不可用时**降级为空（计数显示 0）
   而不是整页 500** —— GIS 地图是站点底图，不该因一张统计表抖动而打不开。
   降级会打 `[gis/sites] <表名> 统计不可用，降级为 0` 的 WARNING，可据此判断是否又撞上了。

**顺带修掉的隐患**：`_detect_gis_schema()` 原为**进程级永久缓存**，表一旦被判定存在就永不复核，
`has_realtime_alarm` 恒为 `True`，兜底判断形同虚设；现改为 `_SCHEMA_TTL=300s` 的 TTL 缓存。

**回归验证**（改这片前先跑）：

```powershell
# 端点正常性
(Invoke-WebRequest 'http://127.0.0.1:7038/api/gis/sites?time_start=2026-09-22&time_end=2026-09-29' -UseBasicParsing).StatusCode
# 全套后端测试（本次改动后 174 passed）
python -m pytest tests\ --ignore=tests\test_frontend_deep.py --ignore=tests\test_frontend_e2e.py -q
```

> **改完必须重启后端才生效**（`pythonw.exe` 常驻，不会热加载）。
> 排障时留意：**日志文件按天命名且随重启更换**，翻错文件会误判成"没报错"。

### 僵尸作业堵死推送通道（2026-10-01 事故）

**现象**：`tt_alarm_whatsapp_alert` 在任务管理页**显示成功**，但值班群**收不到 P1 告警**。
最迷惑的一点是它「自己好了」—— 失效几小时后任务恢复 `success=True`，
其实只是**候选单变成了 0**（同期的单已过 3 小时窗口，或已清除），并不是推送恢复。

**先看这一处**（一行定位）：

```powershell
# 作业文件是不是长期停在 running？
Get-Content D:\01_RPA\Task\my_app\backend\services\data\tt_alert_job.json -Encoding UTF8 |
  ConvertFrom-Json | Select-Object job_id, status, created_at, claimed_at
# 或者直接问扩展轮询端点：正常空闲应返回 {"pending":false}
(Invoke-WebRequest http://127.0.0.1:7038/api/whatsapp/ext/job -UseBasicParsing).Content
```

**根因**：作业文件是**后端 ↔ Chrome 扩展**之间的邮箱（`tt_alarm_job.py`）。
扩展认领即把状态置 `running`（乐观锁，防多实例重复发送），但**认领后可能永不回报**
—— 浏览器被关掉、扩展崩了、或机器上根本没开 Chrome。此时：

- 作业永远停在 `running`，而认领逻辑**只认领 `pending`** → **整个邮箱被永久堵死**；
- 任务侧因为「本轮候选 0 单」提前 `return success=True` → **监控全绿**；
- 期间所有 P1 告警全部发不出去，**群里静默**。

2026-10-01 实测：04:15 起连续 4 轮告警未达（每轮干等 600s），04:55 那单被 09:11
认领后再无回报，直到人工清理。当时机器上只有 msedge、**没有 Chrome 在跑**。

**判定与处置**：

| 判据 | 含义 | 处置 |
| --- | --- | --- |
| `status=pending` 且 `claimed_at=null` | **没有扩展在轮询** | 打开 Chrome 并登录 WhatsApp Web、确认扩展已启用 |
| `status=running` 且 `claimed_at` 很旧 | **僵尸作业**，邮箱已堵 | 该单若已过 SLA 就直接置 `failed`（别补发过期告警）；未过期可等自动回收 |
| `/api/whatsapp/ext/job` 返回非 `pending:false` | 有作业卡着 | 同上 |

手工清理（把 `status` 改成 `failed` 即可放行，**不必重启**）：

```powershell
$p = "D:\01_RPA\Task\my_app\backend\services\data\tt_alert_job.json"
$j = Get-Content $p -Raw -Encoding UTF8 | ConvertFrom-Json
$j.status = "failed"; $j.completed_at = (Get-Date).ToString("s"); $j.result = @{ ok=$false; sent=@(); errors=@("人工清理僵尸作业") }
$j | ConvertTo-Json -Depth 6 | Set-Content $p -Encoding UTF8
```

**已做的修复**（2026-10-01）：

1. **僵尸自动回收** —— `running` 超过 `STALE_RUNNING_SECONDS`（默认 3600s）未回报的作业
   允许重新认领；判定口径收敛在 `backend/services/job_staleness.py`，
   **发图源与告警文本源共用**（两者状态机同构，必须同改）。
   阈值必须**远大于**正常发送耗时，否则多实例会重复发同一批告警。
2. **告警没发出去就吵** —— 有 due 单却一条都没确认发送时，任务产出 `warnings`，
   走 `task_runner.py:545-565` 的**降级告警**通道主动通知（微信+邮件）。
   否则「扩展恢复 → 下轮候选 0 → 立刻 success=True」，这段故障会被彻底埋掉。
3. **投递前先查扩展在线** —— 见下节。把「10 分钟后超时才知道」压成「这一轮就知道」。

> ⚠️ 改了这两处**必须重启后端与 worker 才生效**（`pythonw.exe` 常驻，不热加载）。
> 回归：`python -m pytest tests\test_job_zombie_and_month_start.py tests\test_ext_liveness.py -q`

### P1 告警推送通道（2026-10-01 由扩展切换为 Baileys）

**通道现状**：P1 告警**不再走 Chrome 扩展**，改由
`whatsapp-kb-bot` 的 **`src/notify.js`**（Baileys，WhatsApp WebSocket 协议）发送。

**为什么换**：扩展通道的**全部复杂度都来自「操作网页」** —— 要浏览器常开、要页面聚焦
（粘贴依赖焦点）、每 2~3 周人工扫码，且发送确认只能靠数 DOM 气泡去猜
（WhatsApp 是虚拟列表，气泡会被回收，实测把「已发出」判成失败并重发，
2026-09-29 出过重复告警事故）。Baileys 不碰页面，这些复杂度全部消失，
且发送确认是 `sendMessage()` 返回的**服务端 message id**，不是猜的。

> 发图任务（`whatsapp_send_ext` / `whatsapp_send`）**仍走原通道**，本次只改了 P1 文本告警。

**投递前在线检查**：投递前读推送进程的心跳，离线立刻产出 `warnings`
（把「几分钟后才知道」压成「这一轮就知道」）：

| 状态 | 判据 | 行为 |
| --- | --- | --- |
| `online` | 阈值（默认 300s）内有心跳且 `connected=true` | 静默，正常发送 |
| `offline` | 心跳过期、`connected=false`，**或心跳里的 pid 已不存在** | **立刻**产出 `warnings` 走微信+邮件喊人 |
| `unknown` | 从无心跳（进程刚起/从未启动） | **不告警**，仅记日志 |

> `unknown` 不告警是**刻意的**：进程每次重启都没有心跳，若判离线则每次重启都误报，
> 会让人对告警脱敏。判离线必须**有明确证据**。
>
> **为什么还要查 pid**：心跳文件是进程被强杀时**来不及更新的**。实测
> `Stop-Process -Force` 之后文件里仍是 `connected:true` + 旧时间戳，
> 只看时间戳会有最长 300s 的「假健康」窗口 —— 而这段时间告警投出去其实没人消费。
> 故心跳里带了 `pid`，判活时顺手核对进程是否存在，把窗口压到一次轮询。

**手工排查**：

```powershell
# 1) 状态总览（进程 / 心跳 / 健康判定一句话给全）
powershell -NoProfile -ExecutionPolicy Bypass -File D:\01_RPA\Task\whatsapp-kb-bot\autostart-notify.ps1 -Status

# 2) 直接看心跳
Get-Content D:\01_RPA\Task\whatsapp-kb-bot\data\notify_heartbeat.json -Raw -Encoding UTF8
# 文件不存在 = 推送进程还没起过（unknown）

# 3) 只连不发，自检凭据与连接（不会打扰任何群）
cd D:\01_RPA\Task\whatsapp-kb-bot
node --env-file-if-exists=.env src/notify.js --check

# 4) 群名 → JID（配置里写的是群名，发送要 JID）
node --env-file-if-exists=.env src/notify.js --groups
```

**常驻与看门狗**（2026-10-01 新增）：两个计划任务，注册脚本
`whatsapp-kb-bot\register_notify_tasks.ps1`：

| 任务 | 频率 | 作用 |
| --- | --- | --- |
| `WhatsAppKB_Notify_Autostart` | 登录时 | 开机自启 |
| `WhatsAppKB_Notify_EnsureRunning` | 每 5 分钟 | 进程不在 / 心跳不健康就重启 |

> 两个都要：只做自启的话，进程中途死掉**没人知道**，值班群会静默收不到 P1 告警
> —— 这正是 2026-10-01 事故的形态（监控全绿、业务已坏）。
>
> 巡检脚本判「不健康」包含**活着但未连接**（如凭据失效），此时重启是正确动作。

**单实例保护**：`notify.js` 启动时写 `data\notify.lock`（含 pid）。
已有存活实例时**拒绝启动并说明原因** —— 否则两个实例会各自轮询同一个信箱，
同一作业被消费两次、告警发两遍。锁里的 pid 已死（上次被强杀）会自动回收，不会永久卡死。

**凭据失效怎么办**：推送进程是隐藏运行的，二维码打出来也没人看得见。
心跳会显示 `connected: false`，此时执行 `cd whatsapp-kb-bot` → `npm run relogin` 重新扫码，
再 `autostart-notify.ps1 -Stop` 后重新拉起（或等 5 分钟看门狗）。

### 扩展在线检查（2026-10-01 新增，仅发图通道仍适用）

> ⚠️ **P1 文本告警已不走扩展**（见上一节）。本节只对**发图任务**有效：
> 浏览器没开时图片发不出去，任务会干等 `WAIT_SECONDS` 才发现。

**机制**：扩展每 ~17 秒轮询一次 `/api/whatsapp/ext/job`，后端在认领入口
（`whatsapp_job_claim.claim_next_job()`）把时刻记进
`backend/services/data/ext_liveness.json`；三态判定与上表同构
（`online` 静默 / `offline` 立刻告警 / `unknown` 不告警）。

**为什么不直接自动拉起浏览器**：扩展与发图任务（`whatsapp_service`）**共用同一个
profile**，而后者的 `_kill_stale_chrome()`（`whatsapp_service.py:188`）会按命令行里的
profile 路径**强杀**占用进程 —— 两者共存必然互相残杀。
要自动化须先给扩展配**独立 profile**（需重新扫码登录一次），属独立议题。

**手工排查**：

```powershell
# 扩展最近一次认领是什么时候？超过 5 分钟即视为离线
Get-Content D:\01_RPA\Task\my_app\backend\services\data\ext_liveness.json -Raw -Encoding UTF8
# 文件不存在 = 服务重启后扩展还没来认领过（unknown，属正常冷启动）
```

### `cells_kpi_sync` 每月 1 号报失败（2026-10-01，属预期而非故障）

**现象**：每月 1 号 04:50 报 `2026-10 无有效小区数据，物化 0 行`，
连自动重试也失败，并触发微信+邮件告警；但**次日照常成功**。

**这不是 bug，是月初的正常空窗** —— 但要理解它必须先纠正两个直觉：

**直觉一：「按 `Begin Time` 归属月份是错的」—— 错，口径是对的。**
`Begin Time` **就是**数据覆盖的自然日，不是"窗口起点"。实测 360 万行
`End Time - 1day == Begin Time` 全等。所以 `Begin Time = 2026-09-30` 表示
"这是 9/30 这一天的数据"，**这个取值是对的、也是唯一可能的**。

**直觉二：「数据延迟了，等等/重试就好」—— 错，重试没有用。**
小区可用率是**按天**统计的：一行 = 某小区在某自然日的表现。
**一天没过完，就算不出这一天的数据**，所以任何时刻能取到的最新一天必然是**昨天**。
这不是上游发布慢，而是「今天」这个数据点**此刻根本不存在**。

于是 10/1 04:50 跑、物化 `current_month()=2026-10` 时，窗口要找的是
「10/1 这一天」，而 10/1 还没过完 → 本月窗口内**必然一行都没有**。
加长重试、改窗口都无济于事，必须靠**判据识别**而不是靠等待。

> 用「T+1 发布 / 数据未发布」描述这件事会把人带偏（听起来像上游的问题）。
> 准确的表述是：**天粒度数据在当天结束时才成立**。

**判定**：看是不是「当前月 + 1 号」这一种组合。

```sql
-- 确认任务是否已被标记为预期空窗（PG 主库；SQLite 模式下换 db/app.db）
SELECT started_at, success, error FROM task_execution_log
WHERE task_id='cells_kpi_sync' ORDER BY started_at DESC LIMIT 5;
```

**已做的修复**：`ran_cells_kpi_sync._is_month_start_pending()` 把
「当前自然月 **且** 今天 1 号」的空窗判为**预期**（`month_pending=True`、`success=True`、
`errors` 为空），不再误报。**只豁免这一种组合** —— 历史月为空、或当月 2 号起仍为空，
照旧按真故障处理（那时每一天都已过完，空就是漏采）。

> ⚠️ **月初这天看板是空白的，这是预期**：1 号当天物化库为 0 行，
> **从 2 号凌晨起自动产出**，无需人工干预。若有人问"Cells KPI 怎么是空的"，
> 答案就是「本月数据自 2 号起可用」。**不要**为了"别空着"去填上月的数 ——
> 那会让人误读成这是本月数据。

> 该任务 2026-09-25 才上线，**10/1 是它第一次遇到月份边界**，故此前从未暴露。
> 回归：`python -m pytest tests\test_job_zombie_and_month_start.py -q`

### eFlow 登录风暴：前端打不开 + 上游用户数暴涨（2026-10-04 事故）

**症状**（两个表象，两组独立缺陷）：`?page=portalLogin` 等页面**打不开**（7090 未监听）；
同时 eFlow 上**用户数持续增长**、"几秒一次登录"。

#### 缺陷一：前端路径未随脚本搬迁更新（页面打不开）

提交 `0e6071ed`（2026-10-03 21:58「代理脚本迁出被忽略的 scripts/ 并入 tools/」）
把 `start-app.mjs` 移到 `tools/`，但**没有同步修改 `frontend/package.json`**
（已核对：该提交的文件列表里根本没有它）：

```
frontend/package.json:9,12   "node ../scripts/start-app.mjs"   ← 文件已不在
→ Error: Cannot find module '...\scripts\start-app.mjs'
→ 7090 未监听 → nginx /myapp/ 502 → 页面打不开
```

> **为什么当时没暴露**：该提交自己写明"线上两个代理 ensure_proxy 返回 reuse，
> **未重启**" —— 当时跑的还是搬迁前启动的旧进程，路径错误**只在下次冷启动时**
> 才暴露，而那个时刻落在了 2026-10-04。

**修复**：`frontend/package.json:9,12` 改指 `../tools/start-app.mjs`。

#### 缺陷二：`do_login()` 的两个判据同时错了（登录风暴）

**这是风暴的核心。** `tools/realtime_proxy.py` 的 `do_login()` 有**两个独立错误**，
任一存在都会让"登录明明成功却判定失败"，进而永不写会话、每个请求 403 并再次登录。

**错误 A：csrf 取不到（`c.name == "forgerydefense"` 精确匹配）**

eFlow 的 cookie 名**带端口后缀**，实测为 `forgerydefense-28001`，不是裸名。
原实现用精确相等匹配，**永远匹配不上**，于是 `csrf` 恒为空：

```python
for c in _COOKIE_JAR:
    if c.name == "forgerydefense":     # ← 实际叫 forgerydefense-28001，永不命中
        csrf = c.value
```

现场实测 jar 内容（`forgerydefense-28001` 明明有 64 字节）：
```
Z-AUTH-CODE-28001 = <非空 len=41>
x-dexmesh-user-28001 = <非空 len=64>
forgerydefense-28001 = <非空 len=64>     ← csrf 就在这，但取不到
```

**错误 B：成功判据要求 `"result":"1"`，而 eFlow 恒返回 `"result":"0"`**

```python
result_ok = '"result":"1"' in raw2.decode(...)   # ← eFlow 从来不发这个值
```

实测：**全部历史日志里 `"result":"1"` 出现 0 次，`"result":"0"` 出现 2422 次。**
而同一时刻 `backend.services.auth_manager`（判据只看是否拿到 `Z-AUTH-CODE`）
登录**成功**（cookie 350 字节、forgery_token 64 字节）。
**证明登录一直是成功的，是代理自己判错了。**

> ⚠ **`result:"0"` 不是"被拒绝"语义**，这版 `login_rsa` 恒回 `0`，
> 同时正常签发 `Z-AUTH-CODE` / `forgerydefense` / `x-dexmesh-user`。
> 用 `result` 判断登录成败是本事故最大的认知陷阱 —— 排障时别再把 `result:0`
> 读成"上游拒绝登录"。**判定登录是否成功，看是否拿到会话 Cookie。**

**正反馈如何放大**（`refresh_session` 修复前无任何退避）：

```
冷启动读不到会话 → do_login() 登录成功但判失败 → 返回 ("", "")
  → 会话没写进 _SESSION、没 save_session()
    → 下个请求仍无有效会话 → 403 → 又登录 → 又"失败" → …
      → 实测 10-03 单日 3822 次；上游侧堆 3822 个永不释放的会话
        → 「用户数一直在增加」（my_app 全程没有任何 eFlow 登出逻辑）
```

实测每日 `[auth] login start`：**09-27~10-02 全部 0 次**，**10-03 骤增至 3822 次**。

> **为什么"之前运行的好好的"**：会话文件原先有效时，`do_login()` **从不被执行**
> ——两个判据错误**潜伏已久但从未被触发**。是缺陷一（冷启动丢会话）第一次让它
> 执行到，`refresh_session` 的无退避再把它放大成灾难。
> **不是代码变坏了，是一个一直存在的 bug 终于被执行到了。**

#### 判定（三条命令）

```powershell
# ① 页面打不开：7090 是否在监听
Get-NetTCPConnection -LocalPort 7090 -State Listen
# ② 登录风暴：当天日志首行是 "no valid session file" 而非 "session loaded"
Select-String -Path log\realtime_proxy_fms_*_console.log -Pattern "session loaded|no valid session" | Select-Object -First 5
# ③ 登录次数；正常为个位数，异常时可达数千
(Select-String -Path log\realtime_proxy_fms_*_console.log -Pattern "\[auth\] login start").Count
```

#### 已做的修复

1. `frontend/package.json:9,12` 改指 `../tools/start-app.mjs` —— 恢复 7090。
2. `tools/realtime_proxy.py` 的 `do_login()`：
   **csrf 改用前缀匹配**（兼容裸名与 `-<port>` 后缀）；
   **成功判据改为"拿到 cookie + csrf 即成功"**，与 `auth_manager` 对齐。
3. `tools/realtime_proxy.py` 的 `refresh_session()` **新增三道闸门**：
   成功冷却 `_LOGIN_MIN_INTERVAL`（默认 30s）、失败退避 `_LOGIN_BACKOFF`
   指数增长至 `_LOGIN_BACKOFF_MAX`（默认 600s）、`_LOCK` 串行化。
   均可用环境变量 `PROXY_LOGIN_MIN_INTERVAL` / `PROXY_LOGIN_BACKOFF` /
   `PROXY_LOGIN_BACKOFF_MAX` 现场调参。**被拦下时返回 `("", "")`**，
   避免调用方拿着同一失效会话 `continue` 重试（那会白打一次上游）。
4. `tools/realtime_proxy_vmax.py`：
   - `ensure_login()` 施加同样三道闸门；
   - `forgerydefense` 同样改用前缀匹配；
   - 修掉一个**既存** `UnboundLocalError`：`_proxy()` 的 `except Exception`
     分支从不给 `status` 赋值，上游不可达时抛异常，把本该 502 变成 500 堆栈；
   - `/health` 的 `auth` 判据原先要求 `bool(CSRF)`，但该门户（`10.123.255.12:26180`）
     **只签发 JSESSIONID、从不签发 forgerydefense**，导致登录成功后
     `auth` 仍永久显示 `false`（误导排障）；改为按会话 Cookie 判定。
     `csrf` 单独作为字段暴露。

**验证结果**（2026-10-04 网线恢复后实测）：

```
8787 {"status":"ok","proxy":"ready","target":"https://10.100.20.8:28001","auth":true,"user":"admin"}
8790 {"status":"ok","proxy":"ready","auth":true,"csrf":false,"user":"ZeeshanM"}
tools/fms_session.json 已重建（cookie 有 / csrf 有）
/proxy?url=...getSitedomain?type=RAN → HTTP 200，返回真实站点数据
60 秒内新增 [auth] login start：0 次（修复前为 10~20 次）
```

> **教训一：搬迁脚本时，"按脚本位置推导"的资源路径必须一起搬。**
> 本次受害点是 `dirname(__file__)` 型路径（`realtime_proxy.py:91-92`）。
> 搬迁前应 `git grep` 该文件名找出**所有**引用点 —— `package.json` 就是这样被漏掉的。
>
> **教训二：判定上游成败，要以上游真正给的东西为准，不要臆断字段语义。**
> `result:"0"` 被当成"拒绝"读了很久；真正的成功凭据（会话 Cookie）一直就在响应里。
> **交叉验证手段**：拿同仓库另一条已工作的路径（这里是 `auth_manager`）做对照 ——
> 它成功而这边失败，就说明问题在本侧，不在上游。

> 回归：`python TMP\_verify_proxy_throttle.py`（13 项断言，不触网；
> 覆盖冷却、退避、指数增长封顶、成功后清零）。

> **登录频率治理的回归脚本**（2026-10-04 起，都留在 `TMP/`）：
> - `python TMP/_verify_login_frequency.py` —— **离线**断言（4 项，含"5 次调用 0 次登录"），
>   不触网、不污染上游，**改完鉴权相关代码优先跑这个**。
> - `python TMP/_verify_mw_shared_auth.py` —— **离线**断言（25 项），MW UME 共享鉴权
>   专项：无缓存回退、有效缓存复用、探活失败弃用、损坏 `created_at` 回退、
>   回写正确性、回写→复用闭环。**全程拦截真实登录，绝不触网**。
>   ⚠ 写这类脚本时要**挡对函数**：MW 的 `login()` 走自己的 `_http_request`，
>   **不经过** `auth_manager._do_login`；首版挡错对象，"离线验证"意外登录了上游。
> - `python TMP/_measure_login_rate.py [秒]` —— **在线**实测真实登录次数，
>   判据是 `auth_cache` 的 `created_at` 变化 + 代理日志 `[auth] login start` 增量。
>   它会真的触发上游登录（若缓存确实失效），**跑之前先确认可以接受**。
>
> 📌 **统计口径提醒**：worker 日志按 GBK 落盘，用 `Select-String` 匹配**中文**特征串
> （如"复用共享会话"）会**静默匹配不到**，统计结果假性为 0。做登录计数时
> **一律用 ASCII 特征串**（`LOGIN] Starting authentication` / `LOGIN] SUCCESS`），
> 否则会得出"没有复用"的错误结论。

### 上游会话数控制：TTL 调长 + 登出（2026-10-04）

**背景**：登录风暴的另一半原因是**只登录、从不登出**。eFlow 每次登录都新建一个
服务端会话，而本项目没有任何释放它的代码，于是登录次数直接等于会话堆积量。

#### 1) TTL 调长（已生效）

`backend\.env` 新增 `AUTH_TOKEN_TTL=86400`（1440 分钟 = 24 小时）。
`auth_manager.py:87` 的 `DEFAULT_TTL` 读取它。

**为什么**：`sp_online_sync` 的 cron 是 `35 * * * *`（每小时一次），原默认 TTL
1800 秒（30 分钟）**每次运行前必然过期** → 每小时真实登录一次 ≈ **24 次/天**。
TTL 改为 24 小时后，一天只有第 1 次真实登录，其余命中缓存。

> ⚠ `DEFAULT_TTL` 在**模块导入时求值**，且 `auth_manager.py` **自己不加载 `.env`**
> —— 它依赖 `backend/database.py:9-21` 的 import 副作用先完成 `load_dotenv`。
> 因此改完必须**重启后端与 worker** 才生效，且单独 import `auth_manager` 会读到旧默认值。

**验证**：`python TMP\_verify_auth_ttl.py` → `ALL_TTL_CHECKS_PASSED`
（断言 `DEFAULT_TTL==86400`、缓存文件 `expires_in==86400`、二次读取 `from_cache=True`）。

#### 2) 登出接口：已定位契约，但**尚未验证生效**（默认关闭）

**已确认的部分**（2026-10-04 实测）：

```
POST /api/oauth2/v1/delete/login/remove
Body: {"authCode":["<值>"]}
必需请求头: forgerydefense: <会话 forgerydefense cookie 的值>
```

- 缺 `forgerydefense` 头**一律 403**：`{"code":3329008,"message":"This request
  is prohibited for cross-site access"}`。实测 Referer/Origin 的 7 种组合全部 403，
  **只有**加上该头才返回 204。头名必须是**不带端口后缀的裸 `forgerydefense`**
  —— 用 `forgerydefense-28001` 同样 403（cookie 名带后缀，头名不带）。
- 业务接口同样需要这个头：不带它请求业务 API 也是 403。

**尚未解决的部分 —— `204` 不能作为成功判据**：

| 场景 | 响应 | 该会话随后是否仍可用 |
| --- | --- | --- |
| 用**同一次**登录的 `loginParameters` 当 authCode | 204 | **仍 200** |
| 故意用**陈旧/错误**的 authCode | 204 | **仍 200** |
| 对**已登出过**的会话重复调用 | 204 | — |

**该接口无条件返回 204**，所以它既不证明成功、也不证明 authCode 正确。
我们的实现能拿到 204，但**会话没有被销毁**。

`authCode` 的正确取值**仍未确定**：

| 来源 | 长度 | 结尾 |
| --- | --- | --- |
| 浏览器 F12 抓到的真实 payload | **121** | `$10` |
| 我们从 authorize 页 `loginParameters` 取到的 | **225** | `$10` |

形状一致但长度差一倍，两者都不生效。

> **下一步（需要人工在浏览器操作）**：登录 eFlow → **F12 → Network → 点"注销"** →
> 右键该请求 → **Copy as cURL**，把完整请求贴出（关键是 **Cookie 头全部内容**、
> **所有自定义请求头**、以及 payload 原值）。据此比对才能定值。
>
> 在那之前 `AUTH_LOGOUT_ENABLED` **保持关闭**（默认 False）。实现已就绪：
> 关闭时 `logout()` 直接返回 False 不发请求；开启后即使不生效也**无害**
> —— 幂等、且异常被吞掉不阻断任务。
>
> **判据教训**：早先版本把 `ok = "5" not in status[:1]`（只排 5xx）当成功，
> 于是 **403 被误判为"已登出"**。现已改为**只认 2xx**，并对非 2xx 记
> `[AUTH] 登出未生效`。这个错误是靠**受控对照实验**（同会话、同请求头，
> 唯一变量是"是否登出"）才发现的 —— 单看"请求返回成功"会一直以为它是好的。

#### 3) eFlow 侧会话会自动过期（重要，可能使登出功能变得不必要）

2026-10-04 从 eFlow 的**用户连接数页面**实测到一条关键事实：

| 列 | 值 | 含义 |
| --- | --- | --- |
| **Max Idle Time (Minutes)** | **1440** | 上游自身对会话的**空闲上限就是 1440 分钟 = 24 小时** |
| Idled Time (Minutes) | 0 | 该会话当前空闲时长 |
| Login Time | — | 可用于将列表条目与某次登录对应起来 |
| Operation | Force Logout | 上游提供**手动强制登出**按钮 |

**两个结论**：

1. **堆积的会话会自行回收** —— 空闲满 1440 分钟后消失。所以 2026-10-04 的会话
   堆积**不会永久占用**，不必依赖我们写登出代码去清。
2. **`AUTH_TOKEN_TTL=86400`（= 1440 分钟）与上游上限完全吻合**，是最优取值：
   本地缓存不会晚于上游失效，也不会无谓地触发重新登录。

> ✅ **清理现有堆积会话的首选手段是上游页面的 `Force Logout` 按钮**，
> 不是我们的代码 —— 它直接、可见、无需猜测接口语义。

> ⚠ **排障时务必先确认流量的真实来源。** 2026-10-04 排查中一度把
> 「eFlow 连接数持续增长」归因为 my_app 仍在登录，实测发现当时 my_app
> **一个进程都没跑**，与 eFlow 保持连接的是**本机浏览器**（用户在查看该会话
> 列表页，页面轮询产生大量连接）。
> 判定方法：`Get-NetTCPConnection -RemoteAddress 10.100.20.8` 看 `OwningProcess`，
> 再用 `Get-CimInstance Win32_Process -Filter "ProcessId=<pid>"` 看进程名，
> **不要**只凭"连接数是 my_app 的目标 IP"就下结论。

> **操作纪律**：不要在生产 eFlow 上做密集的登录实验。每次 `get_auth(force_refresh=True)`
> 都会在上游**真实新建一个会话**并出现在用户连接数列表里，直到 1440 分钟后才回收。
> 2026-10-04 的验证过程中因此产生了 11 个测试会话（04:20~04:22）。
> 验证登出这类"会改变上游状态"的功能前，先想清楚**是否会污染生产**，
> 并优先用上游现成的可观测手段（如该列表页）做判定，而非反复打接口。

### 登录频率治理：三道防线（2026-10-04，已实测生效）

**症状**：`AUTH_TOKEN_TTL` 已配 86400（1440 分钟），但登录依然频繁。

**排查结论：TTL 本身是对的，问题是它"管不到"另外两条路径。**
共三个独立缺陷，任一都会导致重复登录：

#### 缺陷 1：`DEFAULT_TTL` 的求值依赖导入顺序（已修）

`DEFAULT_TTL` 在**模块导入时**求值，而 `auth_manager.py` 此前**自己不加载 `.env`**
—— 只在 `backend.database` 被先导入时才"顺带"读到。实测两种结果：

```
先 import backend.database → DEFAULT_TTL = 86400  ✓
直接 import auth_manager    → DEFAULT_TTL = 1800   ✗
```

worker 是多进程（u/n/v/m/c），**导入顺序不受控**，于是"配了 1440 分钟却仍按
30 分钟过期"，且**静默无提示**。

**修复**：`auth_manager.py:81-105` 自己调 `load_dotenv(..., override=False)`，
不依赖任何导入副作用。验证：直接 import 也得到 86400。

#### 缺陷 2：`realtime_proxy` 有**独立**的会话存储，TTL 对它无效（已修）

项目里有**两套 eFlow 会话存储**：

| 存储 | 文件 | 判过期依据 |
| --- | --- | --- |
| `auth_manager` | `backend/services/auth_cache/<host>_<port>.json` | **`expires_in`（TTL）** |
| `realtime_proxy` | `tools/fms_session.json` | 不看 TTL，只看会话是否被拒 |

`realtime_proxy.py` 里对 `AUTH_TOKEN_TTL` 的引用是**零** —— 它自持一份会话，
403 就自己登录。这正是用户最初抱怨的"每个任务申请一次 token"的最后一块拼图。

**修复**：新增 `adopt_shared_session()`（`tools/realtime_proxy.py:178`），
启动时与 403 恢复时都**优先复用 `auth_manager` 的跨进程缓存**，让全项目只有一个 token 来源。

> ⚠ **踩坑记录一（只信 TTL 就采纳 → 502）**：第一版实现**只信 TTL 就直接采纳**缓存会话，
> 结果把一个"看着有效其实已死"的会话当成刷新成功还给调用方 → 重试仍 401 → **502**，
> 比不接共享还糟。日志特征：
> ```
> auth error 401 → shared session adopted (from_cache=True) → attempt=2 → auth error 401
> ```
> **根因**：`auth_manager` 只按 `expires_in` 判过期，而 eFlow 可能**提前**作废会话
> （实测：缓存 `created_at` 才 10 分钟、TTL 86400，请求却返回
> `401 {"hasLogged":true,"source":"smagent",...}`）。
> **修正**：采纳前必须 `_probe_session_alive()` **探活**（打一个轻量只读 API，
> 判据是 HTTP 200）。探活不过就**不采纳**，回退自己的登录流程。
> 同时"会话失效"**不得**被记成"共享永久不可用" —— 那是可恢复的正常状态，
> 缓存在别的进程登录后会变新；只有 import/路径这类结构性错误才永久关闭。

> ⚠ **踩坑记录二（探活函数自己坏了，且静默失败）**：加完探活后，**所有**采纳请求都返回
> "会话已失效"，而同一个会话直接打接口明明是 200 —— 即**探活函数恒 False**，
> 于是共享会话**从未真正生效**，每个请求都退化成自己登录（反而更糟）。
> **根因**：探活函数里写了 `request.Request(...)`（`request` 未绑定）和
> `urllib.error.HTTPError`（该模块只 `from urllib.error import ...`），
> 抛 `NameError`，却被 `except Exception: return False` **静默吞掉**。
> **两条教训**：
> 1. **兜底 `except` 必须打印异常**。`return False` 不写日志，让"探活永远失败"
>    看起来和"会话确实失效"一模一样，排查时极易误判为上游问题。
> 2. **判断"某功能是否生效"要看正向证据**（日志里出现 `probe=ok`、真实取数返回 200），
>    不能只看"没有报错"。本 bug 的离线断言最初还报 PASS —— 因为断言写的是
>    "采纳必须成功"这一**假设**，而不是"会话真的可用"。修完断言与探活才一致。

> 🔎 **附带发现（重要，但不改变本轮结论）**：eFlow 会话可能**提前**失效，
> 与 TTL 无关。实测同一个 `admin` 会话：
> - `04:22` 建的缓存在 `04:39` 前后开始返回 `401 {"hasLogged":true,...}`；
> - 而新登录的会话**立刻可用**，且连续 3 次请求稳定 200；
> - 同时验证：**新登录不会踢掉旧会话**（A 登录 → B 登录 → A 仍 200），
>   即上游**允许多会话并存**，不是"单会话互踢"。
>
> 含义：`AUTH_TOKEN_TTL=86400` 是**上限**，不是保证 —— 会话可能因上游策略
> （空闲回收、重启、安全策略）提前失效。**因此探活是必需的**，
> 只靠 TTL 会在"缓存说有效、实际已失效"时整片 502。
> 上游用户连接页的 `Max Idle Time = 1440` 分钟与此吻合。

#### 缺陷 3：`sp_online_sync` 的触发间隔 > 原 TTL（已修）

`sp_online_sync` 旧 cron 是 `35 * * * *`（每小时），而旧 `AUTH_TOKEN_TTL=1800`（30 分钟）
—— **每轮运行前缓存必然已过期**，于是每小时真实登录一次 = **24 次/天**。

日志完全吻合（修前）：`09-26`~`10-03` 每天 **15/22/23/21/24/21/23/26** 次登录。

**修复**：cron 改为 `35 */6 * * *`（4 次/天，`backend/task_registry.py:665`）。
即使 TTL 配置失效或缓存被清，登录次数也**封顶 4 次/天**，不会退化成 24 次/天。

> 为什么"每小时"本来就不必要：本任务拉的是全量在线工单（非增量流水），
> 看板呈现"当前工单状态"，6 小时粒度对工单场景足够。

#### 验证方法与实测结果

**离线断言**（不触网）：`python TMP/_verify_login_frequency.py`
→ `ALL_LOGIN_FREQUENCY_CHECKS_PASSED`（4/4，含"5 次 get_auth 触发 0 次登录"）。

**在线实测**：`python TMP/_measure_login_rate.py 300`
判据是 `auth_cache` 的 `created_at` 是否变化 + 代理日志 `[auth] login start` 增量
—— **不问代码看起来对不对，只数真实登录次数**。

修复后 5 分钟窗口结果：

| 指标 | 结果 |
| --- | --- |
| 代理 200 响应 | **165 次**（确在满负荷服务） |
| 代理 502 响应 | **0** |
| `auth error 401` | **0** |
| `[auth] login start` | **0** |
| **真实登录次数** | **0** |

即"**165 次成功取数、0 次登录**"。修复前同样流量会触发多次登录。
`/health` 返回 `{"status":"ok","proxy":"ready","auth":true}`，业务取数 200。

#### eFlow 任务全景（改后已全部落在 24h TTL 内）

| 任务 | cron | 间隔 | 说明 |
| --- | --- | --- | --- |
| `eflow_active_alarm` | `*/30 * * * *` | 0.5h | 靠缓存命中 |
| `eflow_sync` | `22 * * * *` | 1h | 靠缓存命中 |
| `eflow_history_alarm` | `0 */3 * * *` | 3h | 靠缓存命中 |
| `sp_online_sync` | `35 */6 * * *` | 6h | **本轮已放宽** |
| `eflow_sync_full` | `0 1 * * *` | 24h | 一天一次，正常 |
| `eflow_tt_rules_check` | `20 4 * * *` | 24h | 正常 |
| `eflow_alarm_rules_collect` / `eflow_push_rules_collect` | `59 23 */3 * *` | 3 天 | 正常 |

**结论**：所有 eFlow 任务的触发间隔都 ≤ 24h，因此**全部命中缓存**，
正常情况下**每天只会有 1 次真实登录**（TTL 到期那次）。

### 登录频率治理（续）：全上游普查与 MW UME 修复（2026-10-04）

eFlow 修完后对**全部上游**做了一次同类缺陷普查（VMAX / MW / IPRAN / CCN /
RAN UME / UME IN / FW / CM / Battery），结论是 **MW UME 比 eFlow 更严重**，
CCN 次之，其余健康。

#### 普查实测：MW 每天 94 次真实登录

按 worker 日志统计**真实登录**次数（10 天）：

| 上游 | 登录次数 | 判定 |
| --- | --- | --- |
| **MW UME** | **935 次**（日均 94） | ⚠ 最严重 |
| UME/RAN | 330 次 | 每天 1~3 次，正常 |
| CNN/CCN | 13 次 | 每天 1 次，正常 |
| IPRAN / eFlow | 0 次 | 正常 |

MW 的时间戳分布是铁证：登录发生在每小时第 **00/15/30/45** 分钟各一次，
与 `mw_ume_kpi_sync_rt` 的 `*/15 * * * *` 完全吻合。

> **为什么长期没被发现**：`backend/worker_watchdog.py:159` 早已写着
> "`mw_ume_kpi_sync_rt` 是 */15 高频任务，实测 **153 次/天**" —— 团队**知道**
> 这个数字，但把它当作**队列调度频率**看（当时是为解决排队 964s 的看板滞后），
> **没人换算成"上游会话数"**。每一次运行 = 一次真实登录 = 上游多一个会话，
> 而 MW 侧从不主动释放。**代价被记在了"调度"账上，没记在"上游会话"账上** ——
> 这是本轮最值得记住的一条：统计口径错了，数字再准也发现不了问题。

#### 根因：与 eFlow 同源的三个缺陷

| 缺陷 | 位置 | 说明 |
| --- | --- | --- |
| 无缓存 | `mw_ume/mw_ume_kpi_service.py:522` `login()` | 每次调都完整走 4 步 OAuth2，函数内无缓存检查 |
| 无失败恢复 | 全文检索 `401\|403\|relogin` **零命中** | 会话中途失效只能整轮失败 |
| 判定过松 | 同文件 `:596-604` | `len(cookies) > 3`、`"portal" in resp_text` 这类猜测式判定 |

#### 修复：接入 `auth_manager` 共享缓存（三件套缺一不可）

MW 的门户路径 `/uportal/framework/default.html` 与 `auth_manager` 内置的
**完全一致**，协议同为 ZTE `login_rsa`，因此可直接接入，无需新写鉴权。

但只"接入"是不够的 —— **实测中发现只做前两步反而更糟**，必须三件套齐备：

1. **`_try_shared_auth()`**（`:461`）—— 复用前先读缓存。
   ⚠ **必须用 `_read_cache()` 而不是 `get_auth()`**：`get_auth()` 不是只读的，
   缓存未命中时它会**直接走到 `_do_login()` 真实登录**（`auth_manager.py:634-646`），
   于是变成"共享没命中 → auth_manager 登录一次 → 本模块又登录一次"的**双重登录**，
   比不接共享更糟。
2. **`_probe_session_alive()`**（`:423`）—— 采纳前探测。
   必须探**业务端点** `HISTORY_PATH`：实测探 `LOGIN_PORTAL` 首页返回 **200**
   （误导性的"看起来正常"），而业务端点返回 **401**。探首页会得到假绿。
3. **`_write_shared_auth()`**（`:496`）—— 登录成功后**回写**缓存。
   这是共享的**另一半**。只读不写时，本模块每轮登录产生的新会话永远进不了
   共享缓存，下一轮探活拿到的仍是旧会话、必然 401 → **每轮白探一遍照样登录**。

#### 实测验证（真机，w 组 worker）

修复过程分三次重启，日志完整记录了三个阶段：

| 时间 | 行为 | 说明 |
| --- | --- | --- |
| 03:35–05:00 | 每轮真实登录 | 修复前 |
| 05:15 | "复用"但**随后 401 失败** | 只做第 1 步：死会话被放行，两个 MW 任务全挂 |
| 05:20 / 05:30 / 05:45 | 探活失败 → 真实登录 | 加了第 2 步：不再挂，但**每轮仍登录**（缓存从不回写） |
| **06:00 / 06:15** | **复用成功、0 登录、200 OK** | 补上第 3 步后闭环 ✅ |

`06:00` 与 `06:15` 两轮日志均为「复用共享会话（auth_manager 跨进程缓存），
跳过登录」，查询 `HTTP/1.1 200 OK`，分别取回 5530 / 4740 行。

> **离线回归**：`python TMP/_verify_mw_shared_auth.py`（25 项断言，**全程拦截真实登录、
> 绝不触网**）。覆盖：无缓存回退、有效缓存复用、探活失败弃用、探活成功复用、
> 损坏 `created_at` 回退、回写正确性、回写→复用闭环。

#### 其余上游评估（无需改动）

| 上游 | 鉴权方式 | 评价 |
| --- | --- | --- |
| IPRAN | 自实现 `login()` + `ensure_session_fresh()` + `_login_lock` + 401 重登（`ipran_ume_kpi_service.py:459-482`） | ✅ 进程内复用与主动刷新最完善 |
| VMAX | `_ensure_session()` 带 `if not self._logged_in` 守卫；代理模式由 8790 代理持会话（`vmax_report_client.py:451`） | ✅ 健康 |
| CM data | 每轮登录一次 + 401 重登（`cm_data_export.py:2088-2096`），cron 每天 | ✅ 低风险 |
| RAN UME | 走 `auth_manager`，`force_refresh=True` 仅用于 401 恢复（`ran_ume_service.py:745`） | ✅ 用法正确 |
| CNN/CCN | 每轮登录，cron 每天 06:00；判定偏松但频率无害 | ⚠ 可择机收紧 |
| FW / UME IN / Battery | 各自 login，均为日级任务 | ✅ 低风险 |

> **一处易错点**：`ipran_ume_kpi_service.py` **并不使用** `auth_manager`，
> 它有自己的 `UmeSessionClient`。用 `grep auth_manager` 判断"是否已接入共享"
> 会把 `ran_ume_*` 与 `ipran_ume_*` 混为一谈 —— 按文件名前缀匹配会漏判，
> 应逐个文件读实现。

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
