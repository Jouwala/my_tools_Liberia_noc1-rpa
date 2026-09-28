# 05 architecture.md —— 架构和数据流

> 基准日期：2026-09-22　|　项目根：`D:\01_RPA\Task\my_app`
> 上级总纲：`D:\01_RPA\architecture.md`（全域拓扑见那里）

> **本文是速查页，不重复手册内容。** 权威正文：
> - 进程拓扑、请求链路、目录结构、前后端分层约定 → `docs\manual\02-architecture.md`
> - SQLite/PostgreSQL 双模、方言适配、Alembic、数据落盘目录 → `docs\manual\03-data-layer.md`
> - 任务注册、队列、worker 分组、看门狗、自动重试 → `docs\manual\04-task-system.md`
> - worker 内部设计细节 → `backend\WORKER.md`

## 一、进程拓扑（一页速查）

```
┌─────────────────────────────────────────────────────────────┐
│  用户浏览器                                                   │
└─────────────────────────────────────────────────────────────┘
                    │ 192.168.100.19:80 (nginx)
        ┌───────────┴────────────┐
        │ /myapp/                │ /api/
        ▼                        ▼
┌──────────────────┐   ┌──────────────────────────────┐
│ 前端 vite :7090  │   │ 后端 uvicorn :7038 (FastAPI) │
│ base=/myapp/     │   │  MY_APP_TASK_QUEUE=1         │
│ 产物 _fe_dist    │   │  ├─ APScheduler 定时触发     │
└──────────────────┘   │  └─ POST /api/tasks/{id}/run │
                       └──────────────────────────────┘
                                     │ enqueue_task()
                                     ▼
                       ┌──────────────────────────────┐
                       │ task_queue 表 (app.db)       │
                       │ status: pending/running/     │
                       │         done/failed          │
                       └──────────────────────────────┘
                                     ▲ 轮询认领
                                     │ (UPDATE...RETURNING 原子操作)
                       ┌──────────────────────────────┐
                       │ Worker 进程（分组 u/n/v/m/c）│
                       │ task_runner.run_task()       │
                       │ → 写 task_execution_log      │
                       └──────────────────────────────┘
                                     ▲ 父进程托管
                       ┌──────────────────────────────┐
                       │ worker_watchdog.py           │
                       │ backend_watchdog.py          │
                       └──────────────────────────────┘
```

## 二、任务系统要点

### 队列设计

- **载体**：SQLite `task_queue` 表（`pending` / `running` / `done` / `failed`），**不引入 Redis/RabbitMQ**。
- **认领**：`UPDATE ... RETURNING` 原子操作，避免多 worker 抢同一任务。
- **单飞保护**：投递前检查同任务是否已有 `pending`/`running` 记录，拒绝重复投递。
- **串行执行**：worker 一次只跑一个任务（UME 单会话互踢、FTP 独占等资源约束）。

### 容错设计（`backend\WORKER.md`）

| 场景 | 行为 |
| --- | --- |
| Worker 停止，队列有 pending | 任务**不丢失**，重启后继续执行 |
| Worker 异常退出留下 running | 下次启动自动标记 `failed`，并补一条 `task_execution_log` |
| Web 投递队列失败（DB 锁等） | 自动降级为**进程内线程执行**，任务不卡死 |
| 未启用队列（无 `MY_APP_TASK_QUEUE=1`） | 行为与改造前完全一致（进程内线程） |
| Worker 进程**静默死亡**（无 watchdog） | Last 冻结、任务不再执行且**无任何报错** —— 这是历史事故根因，故加了看门狗 |
| 看门狗托管 | worker 退出后自动重拉（异常崩溃退避最大 30s，连续 10 次放弃） |

### 任务登记（唯一入口）

`backend\task_registry.py` 的 **`TASK_SPECS`** 是任务声明的**唯一来源**：

- **定义与注册分离**：模块维护 `TASK_SPECS`，`register_all_tasks(task_runner)` 统一注册。
- **懒加载**：业务函数经 `_lazy_loader(module_path, func_name)` 在调用时才 import，避免启动期加载重型服务（UME 登录、playwright、exchangelib），保持后端快速启动。
- **新增任务**：只需在 `TASK_SPECS` 追加一条记录，无需改动注册逻辑。

字段：`task_id` / `name` / `name_en` / `description` / `description_en` / `default_cron` / `category`，二选一提供可执行体 `func` 或 `loader`。详见 `backend\task_registry.md`。

> **新增定时任务不登记 `TASK_SPECS` = 永远不会被执行。**

### Worker 分组的坑（必读）

`MY_APP_WORKER_GROUPS` 控制 worker 分组：

| 值 | 行为 |
| --- | --- |
| 空 | 单 worker 全量执行 |
| `u,n,s,w,m,c,v` | 七组**并行** |

> **新增任务未归组会 pending 卡死。** 新增分组必须**三处同步**：
> 1. `GROUP_TASK_MAP`（后端）
> 2. `start_hidden.ps1`（启动脚本）
> 3. `restart_workers.py`（重启脚本）
>
> 见 `docs\manual\12-configuration.md`。

### 僵尸任务回收

| 环境变量 | 默认 | 作用 |
| --- | --- | --- |
| `WORKER_STALE_RUNNING_SECONDS` | `2160`（30min） | 僵尸 `running` 回收阈值（配合 PID 存活核对） |
| `WORKER_STALE_PENDING_SECONDS` | `21600`（6h） | `pending` 无人认领判陈旧并置 `failed`（释放单飞名额；下限 1800s） |

## 三、数据存储

| 存储 | 位置 | 说明 |
| --- | --- | --- |
| **`app.db`** | `db\app.db` | **主库**（含 `eflow_tt`、告警表、`task_queue`、`credentials`、`task_schedule_config` 等） |
| `eflow.sqlite3` | `data\eflow\` | 工单旧流水线快照（同步**不维护**其 `eflow_tt`） |
| `lbr_ms_sla_kpi.sqlite3` | — | MS SLA KPI 库（**实际文件名带 `lbr_` 前缀**） |
| `db_ps_cs_cn.sqlite3` | **远端**，HTTP `8765` | 本地同名文件是 **0 字节占位** |
| PostgreSQL | 同机 | 迁移目标（规划），`MY_APP_DB_MODE=pg` |

### 数据访问层的已知陷阱

1. **存在绕过 `get_raw_connection` 的裸 `sqlite3.connect`**（如 `ipran_chart_service.py:233`、`fw_kpi_services.py:488`），它们是**图表数据源** —— 统一改造会**静默坏图**。
2. `get_raw_connection` 调用点实测约 **76 处**。
3. **`eflow_tt` 双库**：同步任务**只写 `app.db`**；`eflow.sqlite3` 的副本是旧流水线遗留。
4. **`db_ps_cs_cn` 真数据在远端**（经 HTTP 8765 读），本地是 0 字节占位 —— 误当数据源得到**空结果而非报错**。
5. 告警表 `realtime_alarm` / `history_alarm` 被**同时写** `app.db` 与 `eflow.sqlite3`，但**页面只读 `app.db`**。
6. **`backend\app.db` 是误建的空占位**，真库是 `db\app.db`。

> **现状仍是 SQLite 为主。** SQLite→PostgreSQL 迁移**规划定稿但未执行**（`PROJECT_DOCS.md` §2），执行前提是四项回退保证落地。

## 四、请求链路

```
浏览器 ──► nginx :80
   ├── /myapp/*  ──► vite :7090（前端静态，产物 _fe_dist）
   └── /api/*    ──► :7090 ──► uvicorn :7038（FastAPI）
                        │
                        ├─ routers/  → services/  → get_raw_connection() → SQLite/PG
                        └─ POST /api/tasks/{id}/run → enqueue_task() → task_queue
```

**前端 API 封装**在 `frontend\src\api.ts`。

## 五、分层约定

| 层 | 目录 | 职责 |
| --- | --- | --- |
| 路由 | `backend\routers\` | HTTP 端点，薄层 |
| 服务 | `backend\services\` | 业务逻辑、上游采集、指标计算 |
| 模型 | `backend\models\` | SQLAlchemy ORM |
| 校验 | `backend\schemas\` | Pydantic schema |
| 数据访问 | `backend\database.py`、`dialect_helpers.py` | 连接管理、SQLite/PG 方言适配 |
| 前端页 | `frontend\src\pages\` | 各功能页 |
| 前端组件 | `frontend\src\components\` | 通用组件 |

## 六、配置优先级

**环境变量 > 数据库/配置文件 > 代码默认值**

- `.env` 放在 `backend\.env`（**不入库**，参照 `backend\.env.example`）。
- 全仓库共 **203 个**可被环境变量覆盖的键（统计口径见 `docs\manual\12-configuration.md`）。
- **键名可写，值不可写**（文档纪律）。
- 界面能改的配置（凭据、收件人、远程主机、cron、任务参数）**改完即生效，无需重启**；`.env` 改动**需要重启**。

详见 `docs\manual\12-configuration.md`。

## 七、与统一门户的关系

```
my_app 后端 /api/tasks  ──►  统一门户 TaskSyncWidget（每 60s 轮询，离线降级静态快照）
my_app 页面 ?page=<key>  ──►  门户看板直链（只存相对路径 rel，运行时拼主机）
```

门户架构见 `..\..\liberia-noc_soc-数据看板统一门户\docs\architecture.md`。

## 八、相关文档

| 内容 | 去哪里 |
| --- | --- |
| 进程拓扑与分层（权威） | `docs\manual\02-architecture.md` |
| 数据层（权威） | `docs\manual\03-data-layer.md` |
| 任务系统（权威） | `docs\manual\04-task-system.md` |
| worker 内部设计 | `backend\WORKER.md` |
| 任务注册表字段 | `backend\task_registry.md` |
| 上游集成清单 | `docs\manual\14-integrations.md` |
| 配置项与开关 | `docs\manual\12-configuration.md` |
| 迁移历史与风险 | `PROJECT_DOCS.md` §2（历史档案） |
| 全域拓扑 | `D:\01_RPA\architecture.md` |

> **工具负责整理，人与 AI 负责协作执行。**
