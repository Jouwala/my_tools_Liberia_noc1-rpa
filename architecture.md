# 05 architecture.md —— 架构与数据流

> 基准日期：2026-09-22　|　适用：`D:\01_RPA` 工作区根目录

> **本文只写"整体怎么连"，不重复子系统内部架构。**
> - my_app 内部架构（进程拓扑、请求链路、分层约定）：`Task\my_app\docs\manual\02-architecture.md`
> - my_app 数据层（SQLite/PG 双模、方言适配、Alembic）：`Task\my_app\docs\manual\03-data-layer.md`
> - my_app 任务与调度（注册、队列、worker 分组、看门狗）：`Task\my_app\docs\manual\04-task-system.md`
> - 门户：`liberia-noc_soc-数据看板统一门户\README.md`、`docs\architecture.md`

## 一、部署拓扑（端口级）

```
                    ┌──────────────────────────────────────────┐
   用户浏览器 ──────►│  nginx  192.168.100.19:80                │
                    └──────────────────────────────────────────┘
                       │            │              │
        /myapp/        │   /api/    │  /webroot/   │  /uniplam/
                       ▼            ▼              ▼
              ┌─────────────┐  ┌──────────┐  ┌─────────────┐  ┌──────────────┐
              │ my_app 前端 │  │ my_app   │  │  FineBI     │  │ 统一门户     │
              │ vite :7090  │─►│ 后端     │  │  决策平台    │  │ :9267        │
              │ base=/myapp/│  │ uvicorn  │  │             │  │ + /uniplam/  │
              └─────────────┘  │ :7038    │  └─────────────┘  │   api/*      │
                               └──────────┘                   └──────────────┘
                                    │
                                    ▼
                        SQLite (db\app.db 等) / PostgreSQL
```

**关键端口与路径**（换机房时以 `liberia-noc_soc-数据看板统一门户\src\config.ts` 为准，那是单一真相源）：

| 端口/路径 | 归属 | 说明 |
| --- | --- | --- |
| `80` | nginx | 对外唯一入口 |
| `/myapp/` | my_app 前端 | vite `7090`，`base=/myapp/`，产物目录 `_fe_dist` |
| `/api/` | my_app 后端 | 经 vite `7090` 转发到 uvicorn `7038` |
| `/webroot/decision` | FineBI | 决策报表平台 |
| `/uniplam/` | 统一门户 | 门户前端 + 门户自身后端 API |
| `9267` | 门户开发端口 | `npm run dev`（**不可**复用 7038/7090） |
| `8765` | 远端 SQLite HTTP 服务 | 如 `db_ps_cs_cn`，经 `RemoteDBReader` 读取 |

> **`/uniplam/api` 与 `/api` 必须分清。** 门户前端若请求绝对路径 `/api/auth/login`，会命中 nginx 的通用 `location /api/` 从而打到 my_app 的 7038，POST 被回成 `405`——这正是"其他电脑经 80 端口登录失败"的历史原因。门户因此必须带应用 base 前缀 `/uniplam/api`。原因原文见 `liberia-noc_soc-数据看板统一门户\src\config.ts` 顶部注释。

## 二、三条主要数据流

### 流 1：上游 → my_app（采集与入库）

```
上游系统 (UME / eFlow / CCN / PM / 邮件 / WhatsApp ...)
     │
     │  ① 定时任务触发（task_registry.py 的 TASK_SPECS 登记，worker 分组执行）
     ▼
my_app 后端服务层 (backend\services\)
     │
     │  ② 经 get_raw_connection() / RemoteDBReader(HTTP) 读写
     ▼
SQLite (db\app.db、eflow.sqlite3、lbr_ms_sla_kpi.sqlite3 ...) 或 PostgreSQL
```

**重要事实**（源自 `Task\my_app\PROJECT_DOCS.md` 的全量稽核，做数据相关改动前必读）：

- 运行期存在**绕过 `get_raw_connection` 的裸 `sqlite3.connect`**（已知如 `ipran_chart_service.py:233`、`fw_kpi_services.py:488`），它们是**图表数据源**——任何"统一改数据访问层"的改动都会静默坏图。
- `get_raw_connection` 调用点密集（实测 76 处），不要假设可以一次性替换。
- `eflow_tt` 存在**双库**（`app.db.eflow_tt` 与 `eflow.sqlite3.eflow_tt`）：**同步任务只写 `app.db`**，`eflow.sqlite3` 的副本是旧流水线遗留快照。
- `db_ps_cs_cn` 的**真数据在远端**（`LBR_Tools\KPI\`，经 HTTP `8765` 读），项目内同名本地文件是 0 字节占位。
- 告警表 `realtime_alarm` / `history_alarm` 被**同时写入** `app.db` 与 `eflow.sqlite3`，但**页面只读 `app.db`**。

> 上述内容的完整版与逐条出处见 `Task\my_app\PROJECT_DOCS.md` §2 及其引用的稽核小节。**这些是"规划中的迁移"的前提事实，不是已完成的现状**——目前仍是 SQLite 为主。

### 流 2：my_app → 门户（聚合呈现）

```
my_app 后端 /api/*  ──┐
                      ├──►  统一门户 (React)  ──►  浏览器
看板元数据 (rel 路径)  ──┘
```

- 门户**不复制业务数据**，而是保存每个看板的**相对路径 `rel`**，运行时由「主机 + rel」拼出完整 URL。这样换 IP/域名时只改主机一处，且已持久化到 `localStorage` 的旧数据也能自动跟随。
- 门户每 **60 秒**拉一次 `${PORTAL_API}/api/...`（如 `/api/tasks`）刷新任务调度部件；**接口离线时自动降级为静态快照**，不白屏。
- 门户的 QC 指标分**两档节奏**刷新：全量 = 每 60 分钟网格 + 390 秒（每小时 `:06:30`，紧跟 `eflow_sync` 跑完）；告警 = 每 5 分钟网格 + 30 秒（`:00:30` / `:05:30` …，紧跟 `eflow_active_alarm` 的同步）。用**墙上时钟**对齐，而不是 interval 累加——否则进页面时若是 `:07`，`:06` 同步好的数据要再等 59 分钟才上屏。

### 流 3：FineBI 迁移（进行中）

```
FineBI 报表  ──（逐条替换为）──►  my_app 自研页面 (?page=<PageKey>)
```

- 迁移脚本：`liberia-noc_soc-数据看板统一门户\scripts\migrate_finebi_to_myapp.py`
- 迁移记录与可行性：`Task\my_app\docs\FINEBI_MIGRATION.md`
- 门户 `README.md` 明示：**FineBI 具体报表链接目前仍是目录占位（状态 beta）**，需在门户内"编辑看板配置"逐条替换。

## 三、进程拓扑（my_app 运行时）

my_app 生产不是"一个后端进程"，而是：

```
uvicorn 后端 (:7038)
   ├── worker 分组进程（C / M / N / U / V ...，各有 .pid 文件）
   ├── worker_watchdog.py     —— 守护 worker，负责自动重试
   └── backend_watchdog.py    —— 守护后端
```

- 任务注册表：`Task\my_app\backend\task_registry.py`（`TASK_SPECS`）
- worker 说明：`Task\my_app\backend\WORKER.md`
- 任务清单速查：`Task\my_app\backend\task_registry.md`
- **日常巡检"五个关键进程是否都在"**：`Task\my_app\docs\manual\13-operations.md`

> 新增定时任务**必须**登记到 `TASK_SPECS`，否则不会被执行——同时要同步更新 `04-task-system.md` 的分组表。

## 四、数据存储布局

| 存储 | 位置 | 说明 |
| --- | --- | --- |
| `app.db` | `Task\my_app\db\app.db` | 主库（含 `eflow_tt`、告警表等） |
| `eflow.sqlite3` | `Task\my_app\data\eflow\` | 工单旧流水线快照（同步不维护其 `eflow_tt`） |
| `lbr_ms_sla_kpi.sqlite3` | — | MS SLA KPI 库（注意实际文件名带 `lbr_` 前缀） |
| `db_ps_cs_cn.sqlite3` | **远端** `LBR_Tools\KPI\`，HTTP `8765` | 本地同名文件为 0 字节占位，**不要**当数据源 |
| PostgreSQL | 同机 Docker（规划） | 迁移目标：单实例 + 每域一个 schema（`app_` / `eflow_`） |

**入库纪律**：`db\`、`log\`、`TMP\`、`auth_cache\`、`*.pid`、`native_board_cache\` 均已在 `.gitignore` 中忽略（`db` 约 956M、`log` 约 152M）。**不要**为了"顺便备份"而把它们加进版本库。

## 五、典型请求链路

### 门户加载看板列表
```
浏览器 → /uniplam/ (nginx) → 门户前端 :9267
       → GET /uniplam/api/portal-default   （门户后端提供默认看板配置）
       → 本地 localStorage 覆盖（键 liberia_noc_dashboards_v3）
       → 渲染卡片，每张卡的 URL = 主机 + rel
```

### 门户拉实时任务状态
```
门户 TaskSyncWidget ──60s──► GET /uniplam/api/tasks
                              → （同源部署）nginx → my_app :7038 /api/tasks
                              → 失败则用内置静态快照渲染，不空白
```

### 门户 QC 卡片下钻
```
点击 QC 卡 → GET /uniplam/api/portal-qc/detail?metric=<id>&page=1&size=50[&q=]
           → 返回 { total, rows, columns }
           → 弹窗表格分页；关闭时递增 qcDrillSeq 作废在途请求
```

## 六、安全边界

- 门户鉴权：`server\auth.ts`、`authDb.ts`、`authSwitch.ts`；鉴权用户表在 `auth-data\`（**含加盐密码哈希，已 .gitignore，严禁入库**）。
- 鉴权开关：`auth-switch.json` + `auth_switch.bat` / `auth_switch.py`，说明见 `AUTH_SWITCH.md`。
- my_app 安全现状与**已知风险清单**：`Task\my_app\docs\manual\05-security-and-credentials.md`。
- TLS/凭据：`Task\my_app\backend\security.py`、`security_tls.py`。
- **文档纪律**：可写配置项名称与环境变量键名，**不得**写口令、Token、授权码、账号。

## 七、已知架构风险（改前先读）

| 风险 | 说明 |
| --- | --- |
| 双库 `eflow_tt` | 谁写谁读不明确时极易读错库；写方只有 `sync_from_eflow_api`（写 `app.db`） |
| 远端库本地占位 | 本地 `db_ps_cs_cn.sqlite3` 是 0 字节，误当数据源会得到空结果而非报错 |
| 裸 `sqlite3.connect` | 绕过统一数据访问层，迁移/改造时会静默坏图 |
| nginx 路径冲突 | `/api/` 归 my_app；门户必须走 `/uniplam/api/`，写错会 405 |
| nginx 双份配置 | 本机 (.20) 生效配置在 `D:\01_RPA\nginx-1.28.0\conf\nginx.conf`；`Y:\01_RPA\nginx-1.28.0\conf\nginx.conf` 服务的是 **.19**。**改错一份不生效**，详见下一节 |
| localStorage 覆盖 | 看板数据本地优先，改了 `initialDashboards.ts` 但用户没清缓存时会"看不到新数据"（需"恢复初始默认看板"） |
| 硬编码主机 | 主机集中在 `src\config.ts` 的 `DEFAULT_HOST`，其它地方不应再出现 IP |

## 八、架构决策记录（事实上的 ADR）

> 本仓库无独立 ADR 目录，按 `AGENTS.md` 第三节第 8 条在此追加带日期的决策小节。

### 2026-10-05：P1 告警推送由「eflow_tt 定时窗口扫描」改为「realtime_alarm 触发 + eFlow 实时查单」

**背景。** `tt_alarm_whatsapp_alert`（每 15 分钟）旧机制扫 `eflow_tt` 的 3 小时窗口找
未清除 P1 单，但该表只由 `eflow_sync` **每小时 :22** 落库一次，端到端时延
（告警发生 → 值班群看到）平均 ~45 分钟、最坏 ~75 分钟；且重推是纯时间节流
（工单毫无变化也每 ~30 分钟重发 30 行完整分析，有进展反而不推）。

**决策。** 改为**触发制**（`backend/services/tt_alarm_trigger.py` +
`tt_alarm_sources.py`，编排重写于 `tt_alarm_whatsapp_service.py`）：

1. **触发源换 `realtime_alarm`**（由 `eflow_active_alarm` 同步；注册表默认 `*/30`、
   **实际周期以任务配置页的调度为准**，生产已配置 `*/5`。行带
   `tt_id`/`alarmraisedtime`/`alarmcode`）—— 触发条件：带 TT + 升起时间在触发窗口内 +
   告警码白名单；调度从 `*/15` 提到 `*/5`；
2. **详情实时查单**：复用 `eflow_data_mapper.fetch_tt_live_batch`（一次分页遍历
   base/list 匹配全部目标单）拿当前 `ticket_severity`/`last_modified_time`/
   `alarm_clear_time`，本地 `eflow_tt` 镜像只作停滞老单的兜底；
3. **重报 delta 化**：停滞（距最近一次工单更新 ≥20 分钟）且冷却（距上次成功发送
   ≥20 分钟）才重报并带 `REMINDER` 横幅；工单有更新只记跟踪字段不打扰群里；
   告警清除（`alarm_clear_time` 非空 / 从 realtime_alarm 消失）自然止损；
4. 日志表 `eflow_tt_whatsapp_alert_log` 幂等补列 `last_alarm_seen_time` /
   `last_known_update_time` / `last_check_time`（服务内建表惯例，不走 Alembic）。

**效果。** 首推时延从 45~75 分钟压到分钟级：告警同步周期（生产 `*/5`）+
本任务轮询（`*/5`）+ 实时查单秒级，平均 ~5 分钟、最坏 ~10 分钟；
重报从「定时刷屏」变为「停滞才报」，且值班能靠横幅区分首推与第 N 次提醒。

**代价与注意。**
1. 依赖链变长：`eflow_active_alarm` 挂了触发面就静默变空 —— 已加**表新鲜度检查**
   （`_sync_time` 滞后超过阈值 → warnings 走微信/邮件喊人）。**阈值随实际调度
   自适应**：优先读 `task_schedule_config` 里该任务的生效 cron 推导
   （周期 × 1.5，下限 5 分钟），env `TT_TRIGGER_SYNC_STALE_SECONDS` 可显式覆盖，
   读不到时退回 2700 秒兜底 —— 初始版写死 45 分钟，在用户把周期调到 `*/5` 后
   迟钝 9 倍，2026-10-05 复盘订正；
2. 每轮多一次 eFlow API 分页遍历（仅在有候选单时；会话复用 `auth_manager`
   跨进程缓存，登录风暴整改后该路径安全）；
3. `window_minutes` 配置项语义已变（触发窗口，非 occur 窗口），页面标签已同步；
4. 旧路径（`fetch_candidate_tts`/`is_due`/UNCLEARED_SQL 等）已按「删除优于兼容」移除，
   相关单测重写；`portal_qc.py` 的 `_TT_UNCLEARED` 与本任务不再同源，各自独立演进。

**回滚路径。** revert 本次提交即可恢复旧扫描机制；日志表新列只增不改，
旧代码读它不受影响。

### 2026-10-01：.20 本机 nginx 从网络映射盘 Y: 迁到本地盘 D:

**背景。** MSNOC1（.20）的 nginx 原先运行在 `Y:\01_RPA\nginx-1.28.0\` —— 那是网络映射盘
（`Y:` → `\\192.168.100.19\e`，即 .19 的 E 盘）。**nginx.exe、conf、logs、temp 全部落在 SMB
共享上**：每写一行访问日志、每次 proxy 缓冲落盘都要走一次网络往返。

**触发事件。** 2026-09-30 21:56~22:15，nginx 进程消失、80 端口拒绝连接，两个页面
（`/myapp/`、`/v1/olbrportal/`）同时不可用。取证结论：

- `logs\error.log` 在猝死前**只有 warning 级** `an upstream response is buffered to a temporary
  file ...` 记录，**没有任何 crash / emerg 痕迹**；
- 系统事件日志在 21:50–22:20 区间**无意外关机（41）、无服务崩溃（7031/7034）**，该机当时已连续运行 13 天；
- 上游服务（7038 后端 / 7090 前端 / 8787 实时代理）**全程健康**，故障面严格限定在 nginx 本身。

**判定：SMB 网络盘 I/O 阻塞**（进程被网络盘写入卡死/异常终止，故无 crash 日志）。

**决策：** 把 nginx 复制一份到本地盘 `D:\01_RPA\nginx-1.28.0\` 并在那里运行。

**为什么是「复制」而不是「移动」。** 配置注释（原 `nginx.conf:26`）载明「MSNOC1 与 .19
两台机器的 nginx 往同一批文件里写」——**Y: 上那份 .19 自己也在用**。因此 Y: 原件必须原样保留，
不能搬走也不能删。

**代价与后续约束（重要）：**

1. **配置从此有两份，必须分清改哪份**：本机改 `D:\...\conf\nginx.conf`；`Y:\...\conf\nginx.conf`
   改动只影响 .19。这是本次决策引入的**长期维护成本**，换来的是本机不再依赖 SMB。
2. `D:\01_RPA\nginx-1.28.0\` 是**第三方发行包**，已加入根 `.gitignore`；但它是**线上服务目录**，
   **忽略跟踪 ≠ 可以删除**。
3. 监控与轮转脚本的路径已同步（`nginx_monitor.ps1` Version 4 的 `NginxExe`/`NginxDir`、
   `rotate_nginx_logs.ps1` 的 `-Prefix`）。**两者必须一起改**，否则轮转会去轮转 Y: 上的旧目录。
4. 桌面快捷方式 `olbr_app\nginx-Stop.lnk` 的 `WorkingDirectory` **仍指向 Y:**，未同步更新 ——
   它现在停的是 .19，对本机无效。
5. 附带修复：原先 nginx 以 `E:\01_RPA\nginx-1.28.0` 为 prefix 解析相对路径（`root html;`），
   而本机**不存在 E 盘**，于是 `/favicon.ico`、`/50x.html` 等相对路径请求一直在报
   `CreateFile() ... failed`。迁到 D 盘后 prefix 自然正确，此类报错消失。

**回滚路径。** 停掉 D 盘 nginx → 从 `Y:\01_RPA\nginx-1.28.0\` 启动 → 把
`nginx_monitor.ps1` 的两个路径参数与 `rotate_nginx_logs.ps1` 的 `-Prefix` 改回 Y:。
（服务本身无状态，回滚不涉及数据。）

### 2026-10-06：WhatsApp 知识库机器人补上开机自启与看门狗

**背景。** `Task\whatsapp-kb-bot\` 下有**两个互相独立**的长驻进程，此前只运维了其中一个：

| 进程 | 作用 | 凭据目录 | 本次之前的计划任务 |
| --- | --- | --- | --- |
| `src/index.js` | 知识库问答机器人 | `data/auth` | **无** |
| `src/notify.js` | P1 告警推送 | `data/auth-notify` | 自启 + 看门狗 |

**触发事件。** 2026-10-06 15:15 重启电脑后，推送进程（有任务）自己起来了，
**问答机器人再没起来**。日志显示它最后活动于 `08:25:02`。全工作区检索确认：
`autostart.ps1` **没有任何调用方** —— 唯一的引用是 `autostart-notify.ps1` 里的一句
注释（拿它当写法参照）。即这是**配置缺口**，不是误操作。

**顺带纠正的错误注释。** `src/whatsapp.js` 曾写着「notify.js 与 index.js 共用
`data/auth`，两者只能留一个，否则 440 互相顶号」。该描述**已过时且为假**：
凭据早已拆分（`config.js:48` → `data/auth`，`notify.js:75` → `data/auth-notify`）。
日志佐证：最后一批 440 出现在 10-03，之后两者长期正常并存。

**决策。**
1. 机器人写心跳 `data/bot_heartbeat.json`（`{at, connected, pid}`，30s 刷新，原子写），
   沿用 `notify.js` 的既有做法；
2. `autostart.ps1` 的判活**改为读心跳**。原判据
   `CommandLine -match 'src[\\/]index\.js'` 会把**任何**命令行里含该串的进程认成机器人
   —— 实测把 agent shell 误判为 bot 并写入了 `bot.pid`；
3. 注册四个计划任务（`WhatsAppKB_{Bot,Notify}_{Autostart,EnsureRunning}`），
   注册脚本 `register_whatsapp_tasks.ps1` 取代了只管 notify 的旧脚本；
4. 并入桌面快捷方式体系：`8-start_all` / `9-stop_all` 各增一个阶段，
   新增 `10-start_bot` / `11-stop_bot`，`0-status` 报告心跳。

**为什么用心跳而非进程扫描判活。** **进程活着 ≠ 已连接**：凭据失效或掉线时进程仍在，
只扫进程的看门狗会认为一切正常，而业务消息已经收不到了 —— 这正是 2026-10-01
「监控全绿、业务已坏」事故的形态。心跳同时携带 `connected` 与 `at`，
可区分「进程没了」「进程在但没连上」「进程连上了但卡住」。

**代价与注意。**
1. `9-stop_all` 停掉机器人后，`_EnsureRunning` **最长 5 分钟内会把它拉回来**；
   要长期停用必须先禁用两个任务（控制器结尾会提示）。
2. 停机器人用的是**强杀**：进程跑在隐藏窗口里，`taskkill`（不带 `/F`）发的 `WM_CLOSE`
   无人接收，Node 的 SIGINT 处理也只在真实控制台 Ctrl+C 时触发 —— 实测均无效。
   风险是「写凭据到一半被杀」，极端情况需重新扫码；空闲时停止不受影响。
3. 机器人**不监听端口**，因此任何基于端口的巡检都看不见它，只能靠心跳。

**回滚路径。** `Get-ScheduledTask -TaskName 'WhatsAppKB_*' | Unregister-ScheduledTask -Confirm:$false`
即回到「只有自启、无看门狗」的状态；心跳文件是纯增量产物，删除不影响机器人运行。

## 九、相关文档

| 内容 | 去哪里 |
| --- | --- |
| my_app 内部架构 | `Task\my_app\docs\manual\02-architecture.md` |
| my_app 数据层 | `Task\my_app\docs\manual\03-data-layer.md` |
| my_app 任务系统 | `Task\my_app\docs\manual\04-task-system.md` |
| my_app 集成清单 | `Task\my_app\docs\manual\14-integrations.md` |
| 门户部署（nginx 配置片段） | `liberia-noc_soc-数据看板统一门户\README.md` |
| 迁移历史与复盘 | `Task\my_app\PROJECT_DOCS.md`（历史档案） |
| 商用就绪度整改 | `liberia-noc_soc-数据看板统一门户\MsPortal 商用就绪度检测 —— 结论与整改方案.md` |

> **工具负责整理，人与 AI 负责协作执行。**
