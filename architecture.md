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
| localStorage 覆盖 | 看板数据本地优先，改了 `initialDashboards.ts` 但用户没清缓存时会"看不到新数据"（需"恢复初始默认看板"） |
| 硬编码主机 | 主机集中在 `src\config.ts` 的 `DEFAULT_HOST`，其它地方不应再出现 IP |

## 八、相关文档

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
