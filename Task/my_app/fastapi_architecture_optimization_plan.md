# my_app FastAPI 架构优化计划（方案A）

> 评估时间：2026-08-05
> 目标：在保持 FastAPI 技术栈的前提下，通过 5 个阶段的渐进式重构，解决随功能增长积累的架构债务，使项目可持续扩展。

---

## 一、架构现状评估

### 1.1 项目规模

| 维度 | 数据 |
|---|---|
| 后端 Python 文件 | 62 个，约 **31,123 行** |
| 前端 TypeScript/TSX 文件 | 36 个，约 394 KB |
| 主数据库 app.db | **147 MB**（WAL 文件 11.78 MB） |
| 定时任务 | **27 个**（task_registry.py 声明式注册） |
| 前端页面 | **13 个**（计划集成 IP Trace / Incident Overview 至 15 个） |
| API Router | 9 个独立 router + main.py 内嵌若干端点 |
| Service 层 | **39 个文件**，最大单文件 118 KB |

### 1.2 技术栈

| 层 | 技术 |
|---|---|
| 后端框架 | FastAPI (ASGI) + uvicorn |
| ORM/数据库 | SQLAlchemy 2.0 + 原生 sqlite3 混用 |
| 任务调度 | APScheduler BackgroundScheduler（进程内线程池） |
| 数据库 | SQLite（主库 app.db + 多个辅助库） |
| 前端框架 | React 19 + Vite 8 + TypeScript |
| UI 组件 | Ant Design 6 + ECharts 6 + Leaflet/react-leaflet |
| 鉴权 | IP 白名单 + 静态 X-API-Token（security.py） |

### 1.3 架构分层现状

```
backend/
├── main.py (432行)          ← 直接定义 ~120 行业务端点 + 路由注册 + 启动逻辑
├── routers/ (9个文件)        ← 模块化路由
│   ├── gis.py (883行)
│   ├── alarm_dashboard.py (613行)
│   ├── tt_wo_dashboard.py (460行)
│   ├── battery_dashboard.py (457行)
│   ├── packet_loss_dashboard.py (252行)
│   ├── analysis.py (306行)
│   ├── tables.py (190行)
│   ├── upload.py (156行)
│   └── credentials.py (118行)
├── services/ (39个文件)      ← 业务逻辑层
│   ├── eflow_api_client.py (118KB)    ← 最大
│   ├── ms_sla_service.py (118KB)      ← 最大
│   ├── site_outage_service.py (50KB)
│   ├── ran_ume_network_kpi.py (50KB)
│   ├── ran_ume_main_kpi.py (48KB)
│   ├── task_runner.py (48KB)
│   ├── ipran_ume_kpi_service.py (53KB)
│   ├── ccn_ume_kpi_service.py (40KB)
│   ├── sp_dashboard.py (39KB)
│   ├── battary_kpi_fetch/battery_kpi_service.py (47KB)
│   └── ... (其余 29 个文件)
├── models/ (2个文件)         ← ORM 模型几乎缺失
│   └── analysis.py (32行)
├── database.py (124行)       ← 连接管理 + _ClosingConnection
├── security.py (27行)        ← IP白名单 + Token
└── task_registry.py (294行)  ← 声明式任务清单 TASK_SPECS
```

### 1.4 数据库表分布

| 表来源 | 表名 | 创建方式 |
|---|---|---|
| 代码 CREATE TABLE | task_schedule_config | task_runner.py |
| 代码 CREATE TABLE | task_execution_log | task_runner.py |
| 代码 CREATE TABLE | credentials | credential_store.py |
| 代码 CREATE TABLE | uploaded_files | main.py |
| 代码 CREATE TABLE | sp_sync_log | get_sp_table.py |
| 代码 CREATE TABLE | analysis_archive | scripts/init_db.py |
| 代码 CREATE TABLE | packet_loss_data / site_pl_summary / pl_meta | packet_loss_service.py |
| 代码 CREATE TABLE | battery_latest / battery_reading / battery_trend / battery_meta | battery_kpi_service.py |
| eFlow 同步动态创建 | eflow_tt / eflow_wo / eflow_cr / eflow_pm / eflow_site / eflow_person | sync_from_eflow_api.py |
| 外部导入 | master_site_db / topology | import_topology.py |

### 1.5 六大问题诊断

**问题1：ORM/Model 层几乎缺失（严重度：高）**

`models/` 目录仅有 `analysis.py`（32 行）。所有其他表通过 raw SQL `CREATE TABLE IF NOT EXISTS` 管理：
- 无 migration 管理，多机部署 schema 变更无法自动迁移
- 表结构不透明，调试/扩展需翻阅散落各处的 SQL 字符串
- 数据完整性无 ORM 层保障

**问题2：main.py 承载过多职责（严重度：中）**

main.py 432 行中约 120+ 行是直接定义的业务 API 端点：
- `/api/tasks*` 系列（约 10 个端点）
- `/api/sp-data/*`、`/api/data`、`/api/warehouses`、`/api/details`（SP 备件看板）
- `/api/health`、`/api/data-source/timestamps`、`/api/db/info`（系统信息）

修改任一业务功能都要动 main.py，路由注册与业务逻辑混杂。

**问题3：Service 单文件过大（严重度：中）**

| 文件 | 大小 | 混合职责 |
|---|---|---|
| eflow_api_client.py | 118 KB | HTTP客户端 + 数据映射 + 告警解析 + FTP |
| ms_sla_service.py | 118 KB | SLA计算 + 报表生成 + 邮件 + FTP |
| site_outage_service.py | 50 KB | 截图 + 数据处理 + 文件管理 |
| task_runner.py | 48 KB | 调度核心 + 统计查询 + 调用链分析 |
| report/mail_126.py | 48 KB | 邮件发送 + 附件处理 + 模板渲染 |

**问题4：SQLite + 进程内调度并发瓶颈（严重度：高）**

- 27 个定时任务 + Web 请求在**同一进程**内，APScheduler 线程池（默认 10 线程）
- SQLite 单写锁：多任务同时写 app.db 时串行等待（busy_timeout=30s）
- app.db 已达 147 MB，历史数据持续增长，查询性能将下降
- 多个辅助 SQLite 库分散管理（battery_kpi.sqlite3、lte_pl.sqlite3、db_ps_cs_cn.sqlite3）

**问题5：鉴权体系薄弱（严重度：低-中）**

- 仅 IP 白名单 + 静态 Token，无用户账户体系
- 无角色/权限控制，无操作审计日志
- 使用人数增加或需区分权限时将成为瓶颈

**问题6：前端无路由库 + 无全局状态管理（严重度：低）**

- 用 `useState` 管理当前页面，无 react-router，无法深链接
- 无 Zustand/Redux，跨页面数据共享困难

### 1.6 迁移 Django 对比结论

| 维度 | 继续 FastAPI + 架构优化 | 迁移 Django |
|---|---|---|
| 工作量 | 约 18-21 人天（3-4 周） | 约 26-32 人天（4-6 周） |
| 风险 | 低（增量改造，前端零改动） | 高（全量重写，回归风险大） |
| ORM/Migration | Alembic（完全等价） | 内置（更便利） |
| 任务调度解耦 | 独立 Worker 进程（等价） | Celery + Redis（等价） |
| 异步性能 | FastAPI 原生异步 优势保留 | Django 4.x async 仍不成熟 |
| 免费 Admin | 无（需 fastapi-admin 或自建） | Django Admin 内置 |
| 团队学习成本 | 低（已有 SQLAlchemy 基础） | 中（Django 约定多） |

**结论：不建议迁移 Django。** 当前痛点根源在架构组织而非框架选型，同样的组织问题在 Django 中也会出现。通过 5 阶段渐进优化可解决全部已知问题。

---

## 二、Phase 1 — main.py 端点拆分

**工时估算：2 天**

### 2.1 目标

main.py 仅保留：app 创建、CORS 配置、router 注册、startup 事件、静态文件挂载。
所有业务端点下沉到对应 router。

### 2.2 改动清单

| 操作 | 文件 | 说明 |
|---|---|---|
| 新建 | `routers/tasks.py` | 迁移 /api/tasks* 全部端点（list / history / failures / {task_id} / run / status / stats / schedule / toggle）+ /api/eflow/sync、/api/eflow/status |
| 新建 | `routers/sp_dashboard.py` | 迁移 /api/sp-data/*、/api/data、/api/warehouses、/api/details |
| 新建 | `routers/system.py` | 迁移 /api/health、/api/data-source/timestamps、/api/db/info |
| 修改 | `main.py` | 删除迁移出的端点代码，新增 `app.include_router()` 注册 3 个新 router |

### 2.3 预期效果

- main.py 从 432 行缩减至约 120 行
- 所有 API 路径与返回结构**完全不变**（前端零改动）
- 新增/修改业务端点时只需关注对应 router 文件

### 2.4 验证方式

1. 启动后端，`GET /api/health` 正常返回
2. `GET /api/tasks` 返回任务列表，结构与迁移前一致
3. `GET /api/sp-data/summary`、`GET /api/data`、`GET /api/db/info` 逐一验证
4. 现有前端页面（DataSync、WarehouseDashboard 等）功能回归无异常

---

## 三、Phase 2 — Model 补全 + Alembic Migration

**工时估算：4-5 天**

### 3.1 目标

- 所有表有 SQLAlchemy 模型定义（显式或反射）
- schema 变更通过 Alembic migration 管理
- 保留 `get_raw_connection` 供动态表查询，ORM 会话用于结构化读写

### 3.2 改动清单

#### 3.2.1 补建 ORM 模型

| 新建文件 | 对应表 |
|---|---|
| `models/task_schedule.py` | task_schedule_config |
| `models/task_execution.py` | task_execution_log |
| `models/credential.py` | credentials |
| `models/uploaded_file.py` | uploaded_files |
| `models/sp_sync.py` | sp_sync_log |
| `models/analysis.py`（扩展） | analysis_archive（已有模型则复用） |
| `models/packet_loss.py` | packet_loss_data / site_pl_summary / pl_meta |
| `models/battery.py` | battery_latest / battery_reading / battery_trend / battery_meta |
| `models/eflow.py` | eflow_tt / eflow_wo / eflow_cr / eflow_pm / eflow_site / eflow_person |
| `models/site.py` | master_site_db / topology |

#### 3.2.2 引入 Alembic

```bash
cd d:\01_RPA\Task\my_app
pip install alembic
alembic init alembic
```

- 修改 `alembic/env.py`：导入 `backend.database.Base.metadata`，配置 `target_metadata`
- 修改 `alembic.ini`：`sqlalchemy.url` 指向 `db/app.db`
- 生成初始 baseline：`alembic revision --autogenerate -m "baseline"`
- 对现有库标记：`alembic stamp head`（跳过已存在的表结构）

#### 3.2.3 逐步替换 raw SQL

- 新增/修改数据时优先使用 ORM 会话（`SessionLocal()`）
- 动态表查询（如 `PRAGMA table_info`、`SELECT name FROM sqlite_master`）保留 `get_raw_connection`
- 删除散落的 `CREATE TABLE IF NOT EXISTS`，改由 Alembic migration 管理

### 3.3 验证方式

1. `alembic upgrade head` 在空库上建出与现库一致的表结构
2. `alembic downgrade base` + `alembic upgrade head` 幂等可重复
3. 现有 API 回归：`GET /api/tasks`、`GET /api/db/info` 等正常
4. 新增一条 migration 验证流程：修改某模型字段 → `alembic revision --autogenerate` → `alembic upgrade head`

---

## 四、Phase 3 — 任务调度解耦

**工时估算：4 天**

### 4.1 目标

27 个定时任务不再与 Web 进程争抢线程/DB 锁。Web 进程专注 API 响应，任务执行在独立 Worker 进程。

### 4.2 方案选型

| 方案 | 优点 | 缺点 | 适用场景 |
|---|---|---|---|
| **独立 Worker 进程（推荐）** | 改动最小；不引入 Redis/RabbitMQ；符合"无外部依赖"约束 | 需自建进程间通信（SQLite 任务队列表） | 当前规模（27 任务、单机部署） |
| Celery + Redis | 成熟方案；支持分布式；任务重试/超时管理完善 | 引入 Redis 依赖；部署复杂度增加；学习曲线 | 未来多机扩展 |

**推荐方案：独立 Worker 进程**

### 4.3 改动清单

#### 4.3.1 task_runner 改造

- 新增 `worker` 模式：`task_runner.py` 支持 `--worker` 参数启动纯 Worker 进程
- Web 进程：仅运行 APScheduler 调度器，触发任务时写入 `task_queue` 表（新增）
- Worker 进程：轮询 `task_queue` 表，取出待执行任务，执行后更新 `task_execution_log`
- 重型任务（RAN UME、eFlow 同步、邮件类）标记为 `async_exec=True`，强制走 Worker

#### 4.3.2 新增 task_queue 表

```sql
CREATE TABLE IF NOT EXISTS task_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    trigger TEXT NOT NULL DEFAULT 'scheduled',
    status TEXT NOT NULL DEFAULT 'pending',  -- pending / running / done / failed
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    result TEXT,
    error TEXT
);
```

#### 4.3.3 启停脚本更新

- `start.bat` 增加启动 worker 进程：`start /B python -m backend.worker`
- `stop.bat` 增加终止 worker 进程逻辑

### 4.4 验证方式

1. 仅启动 Web 进程（不启动 Worker），`GET /api/health` 响应时间 < 100ms
2. 启动 Worker，手动触发重型任务（如 eFlow 同步），Web 接口响应不受影响
3. `GET /api/tasks` 中任务执行历史正常落库
4. 停止 Worker，任务排队不丢失（pending 状态保留在 task_queue 表中）

---

## 五、Phase 4 — Service 大文件拆分

**工时估算：5-7 天**

### 5.1 目标

单文件 < 1500 行，职责单一。每个 service 文件聚焦一个明确的业务域。

### 5.2 拆分清单

#### 5.2.1 eflow_api_client.py (118 KB) → 3 个文件

| 新文件 | 职责 | 预估行数 |
|---|---|---|
| `eflow_api_client.py` | HTTP 客户端、认证、重试、连接池 | ~800 行 |
| `eflow_data_mapper.py` | 数据映射、字段转换、入库逻辑 | ~600 行 |
| `eflow_alarm_service.py` | 实时/历史告警解析与存储 | ~500 行 |

#### 5.2.2 ms_sla_service.py (118 KB) → 3 个文件

| 新文件 | 职责 | 预估行数 |
|---|---|---|
| `ms_sla_sync.py` | SLA 数据同步（API 拉取 + 入库） | ~700 行 |
| `ms_sla_report.py` | 报表生成（Excel/图表） | ~500 行 |
| `ms_sla_email.py` | 邮件发送（名单获取 + 发送逻辑） | ~400 行 |

#### 5.2.3 task_runner.py (48 KB) → 3 个文件

| 新文件 | 职责 | 预估行数 |
|---|---|---|
| `task_runner.py` | 调度核心（注册、调度、执行） | ~600 行 |
| `task_stats.py` | 统计查询（成功率、耗时、历史） | ~300 行 |
| `task_introspect.py` | 调用链静态分析、源码解析 | ~200 行 |

#### 5.2.4 邮件公共逻辑抽取

| 新文件 | 职责 |
|---|---|
| `services/email/__init__.py` | 邮件包入口 |
| `services/email/sender.py` | 通用邮件发送（SMTP/EWS） |
| `services/email/recipient.py` | 远程名单获取与解析 |
| `services/report/mail_126.py` | 保留，但调用 sender.py 公共接口 |

### 5.3 约束

- `task_registry.py` 中的 `loader` 入口函数名**不变**，保证任务注册零改动
- 拆分后的模块通过 `__init__.py` 暴露与原文件相同的公共接口，外部 import 路径不变
- 每个新文件同目录配 MD 文档（遵循 code_rules.md）

### 5.4 验证方式

1. 27 个任务逐一通过 `POST /api/tasks/{task_id}/run` 手动触发，确认执行成功
2. `pytest tests/` 全部通过
3. grep 扫描确认无残留的旧 import 路径
4. 各 service 文件行数 < 1500 行

---

## 六、Phase 5 — 数据库升级评估（可选触发）

**工时估算：3 天（仅评估+预案，不立即执行）**

### 6.1 触发条件

满足以下**任一**条件时启动本阶段：

| 指标 | 阈值 |
|---|---|
| app.db 文件大小 | > 500 MB |
| 并发操作用户数 | > 5 人 |
| "database is locked" 错误频率 | > 5 次/天 |
| 单次查询 P95 延迟 | > 2 秒 |

### 6.2 升级路径：SQLite → PostgreSQL

#### 6.2.1 SQLAlchemy 层切换

```python
# database.py 改造（DATABASE_URL 从环境变量读取）
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    f"sqlite:///{DB_PATH}"  # 默认 SQLite，切换时设置 DATABASE_URL=postgresql://...
)
```

- SQLAlchemy ORM 层无需改动（已使用标准 API）
- Alembic migration 重跑：`alembic downgrade base` → 切换 DATABASE_URL → `alembic upgrade head`
- `get_raw_connection` 需适配 PostgreSQL（psycopg2 连接）

#### 6.2.2 数据迁移

```bash
# 使用 pgloader 或自定义脚本迁移数据
pgloader sqlite:///db/app.db postgresql://user:pass@host/dbname
```

#### 6.2.3 辅助库统一归口

| 当前分散库 | 归口策略 |
|---|---|
| battery_kpi.sqlite3 | 合并至主库（PostgreSQL schema: battery） |
| lte_pl.sqlite3 | 合并至主库（PostgreSQL schema: packet_loss） |
| db_ps_cs_cn.sqlite3 | 合并至主库（PostgreSQL schema: core_network） |
| ipran_ume_kpi.sqlite3 | 合并至主库（PostgreSQL schema: ipran） |
| fw_db.sqlite（远程） | 保持独立（跨设备，API 写入） |

### 6.3 历史数据归档策略

对 eflow_tt 等大表（随时间持续增长）：
- 按月分区：`eflow_tt_202601`、`eflow_tt_202602`...
- 超过 6 个月的数据归档至 `eflow_tt_archive` 表（只读）
- 前端查询默认走活跃分区，归档查询走专用 API

### 6.4 当前结论

app.db 147 MB 仍在 SQLite 舒适区（SQLite 理论上限 281 TB，实际推荐 < 1 GB）。Phase 5 暂列为**评估与预案**，不立即执行。当触发条件满足时再启动。

---

## 七、总览

### 7.1 五阶段依赖关系

```mermaid
graph LR
    P1[Phase 1: main.py 拆分] --> P3[Phase 3: 任务调度解耦]
    P2[Phase 2: Model + Alembic] --> P3
    P4[Phase 4: Service 拆分]
    P5[Phase 5: 数据库升级评估]
    P1 --> P2
    P3 -.->|按需| P5
```

- Phase 1 和 Phase 2 可部分并行（Phase 1 先完成 router 拆分，Phase 2 补建模型）
- Phase 3 依赖 Phase 1（需要 router 拆分完成后才能 cleanly 分离 Web/Worker 进程）
- Phase 4 独立，可随时启动
- Phase 5 按需触发

### 7.2 总工时估算

| 阶段 | 工时 | 优先级 |
|---|---|---|
| Phase 1: main.py 拆分 | 2 天 | 高（立即可做） |
| Phase 2: Model + Alembic | 4-5 天 | 高 |
| Phase 3: 任务调度解耦 | 4 天 | 中 |
| Phase 4: Service 拆分 | 5-7 天 | 中 |
| Phase 5: 数据库升级评估 | 3 天 | 低（按需触发） |
| **合计** | **18-21 人天（3-4 周）** | |

### 7.3 风险与回滚策略

| 风险 | 概率 | 影响 | 回滚策略 |
|---|---|---|---|
| Phase 1 router 拆分导致 API 路径变化 | 低 | 高 | Git 回退；API 路径不变是硬约束 |
| Phase 2 Alembic migration 与现有表冲突 | 中 | 中 | `alembic stamp head` 标记现有库；空库测试先行 |
| Phase 3 Worker 进程任务丢失 | 中 | 高 | task_queue 表持久化；Worker 重启后自动恢复 pending 任务 |
| Phase 4 拆分后 import 路径断裂 | 低 | 中 | `__init__.py` 暴露兼容接口；grep 扫描验证 |
| Phase 5 PostgreSQL 迁移数据丢失 | 低 | 极高 | 迁移前完整备份；迁移后逐表行数校验 |

### 7.4 各阶段验收标准

| 阶段 | 验收标准 |
|---|---|
| Phase 1 | main.py < 150 行；所有 API 端点 curl 验证通过；前端页面无回归 |
| Phase 2 | 所有表有 ORM 模型；`alembic upgrade head` 空库可建；现有 API 回归正常 |
| Phase 3 | Web 进程与 Worker 进程可独立启停；重型任务执行时 /api/health 响应 < 100ms |
| Phase 4 | 所有 service 文件 < 1500 行；27 个任务手动触发全部成功；pytest 通过 |
| Phase 5 | 完成 PostgreSQL 迁移方案文档；数据迁移脚本在测试环境验证通过 |

---

## 附录：文件改动总览

### Phase 1 新增/修改

```
backend/routers/tasks.py          (新建)
backend/routers/sp_dashboard.py   (新建)
backend/routers/system.py         (新建)
backend/main.py                   (修改：删除迁移端点，新增 include_router)
```

### Phase 2 新增/修改

```
backend/models/task_schedule.py   (新建)
backend/models/task_execution.py  (新建)
backend/models/credential.py      (新建)
backend/models/uploaded_file.py   (新建)
backend/models/sp_sync.py         (新建)
backend/models/packet_loss.py     (新建)
backend/models/battery.py         (新建)
backend/models/eflow.py           (新建)
backend/models/site.py            (新建)
alembic/                          (新建目录)
alembic.ini                       (新建)
backend/requirements.txt          (修改：新增 alembic)
```

### Phase 3 新增/修改

```
backend/worker.py                 (新建)
backend/services/task_runner.py   (修改：支持 worker 模式)
start.bat                         (修改：增加 worker 启动)
stop.bat                          (修改：增加 worker 终止)
```

### Phase 4 新增/修改

```
backend/services/eflow_data_mapper.py       (新建)
backend/services/eflow_alarm_service.py     (新建)
backend/services/ms_sla_sync.py             (新建)
backend/services/ms_sla_report.py           (新建)
backend/services/ms_sla_email.py            (新建)
backend/services/task_stats.py              (新建)
backend/services/task_introspect.py         (新建)
backend/services/email/__init__.py          (新建)
backend/services/email/sender.py            (新建)
backend/services/email/recipient.py         (新建)
backend/services/eflow_api_client.py        (修改：瘦身)
backend/services/ms_sla_service.py          (修改：瘦身或拆分)
backend/services/task_runner.py             (修改：瘦身)
backend/services/report/mail_126.py         (修改：调用公共接口)
```
