# 01 AGENTS.md —— AI 进入本项目首先需要知道的信息

> 基准日期：2026-09-22　|　项目根：`D:\01_RPA\Task\my_app`
> 上级总纲：`D:\01_RPA\AGENTS.md`（工作区级约束，**先读那个**）

## 一、这个项目是什么

**my_app / Data Insight MVP** —— 利比里亚电信网络运维的**自研数据平台**，是整个工作区的数据底座。它负责把上游系统（UME、eFlow、CCN、PM、邮件、WhatsApp 等）的数据采集、入库、计算、展示，并提供 23+ 个功能页面与 40+ 个定时任务。

**技术栈**：后端 FastAPI + SQLAlchemy（SQLite / PostgreSQL 双模）+ Alembic + APScheduler；前端 React + Vite；任务由多组 worker 进程执行 + 看门狗守护。

**权威文档**：`docs\manual\`（13 份手册，**现状以它为准**）。

## 二、新会话上手顺序

```
1. 本文（约束与地图）
2. docs\manual\README.md     —— 手册导航与"三条阅读路径"
3. docs\manual\01-overview.md    —— 项目定位、能力边界、术语表
4. docs\manual\02-architecture.md —— 进程拓扑、请求链路、分层约定
5. 按任务类型选读：
   - 改功能页     → docs\manual\11-feature-guide.md
   - 改数据层     → docs\manual\03-data-layer.md
   - 改任务/调度  → docs\manual\04-task-system.md（+ backend\WORKER.md）
   - 配置/环境    → docs\manual\12-configuration.md
   - 排障/日志    → docs\manual\13-operations.md
   - 接口/任务速查 → docs\manual\90-appendix.md
```

## 三、硬性约束（违反会直接出问题）

1. **新增功能页必须三处同步**：`frontend\src\App.tsx` 的菜单数组 + `frontend\src\i18n.tsx` 中英**两处** + `docs\manual\11-feature-guide.md`。**漏一处，手册就和界面对不上**（`docs\manual\README.md` 维护约定第 1 条）。
2. **新增定时任务必须登记** `backend\task_registry.py` 的 `TASK_SPECS`，否则**根本不会被执行**；同时更新 `docs\manual\04-task-system.md` 的分组表。
3. **前端构建产物目录必须是 `_fe_dist`**，否则后端找不到静态文件会白屏（`docs\manual\10-quickstart.md`）。
4. **帮助文档是生成文件，不要手改。** `docs\manual\15-user-help.md` 与 `15-user-help-en.md` 的源在 `frontend\src\pages\helpContent.ts` 与 `helpTaskDocs.ts`；改完跑 `cd frontend && node scripts\generate-help-doc.mjs` 重新生成。改了 TS 不重新生成 = 站内帮助与 MD 不一致。
5. **不写敏感值。** 手册里可写**配置项名称**、**环境变量键名**、**分组 key**；**不得**写口令、Token、授权码、内网主机名、账号。参见 `docs\manual\05-security-and-credentials.md` 末尾的禁写清单。
6. **每条论断带出处。** 写"某某行为"时标注 `文件路径:行号`，便于代码演进后定位失效内容（`docs\manual\README.md` 维护约定第 4 条）。
7. **不要把现状写回 `PROJECT_DOCS.md`。** 那是**历史档案**（迁移计划、架构评估、i18n 审计、失败复盘），其 README 已声明"现状以 `docs\manual\` 为准"。
8. **中文注释。**
9. **不入库。** 见下节。

## 四、不入库清单（`.gitignore` 已覆盖，禁止绕开）

| 忽略项 | 原因 |
| --- | --- |
| `/db/` | SQLite 约 956M（`db\app.db` 是真库） |
| `/log/` | 运行日志约 152M |
| `/TMP/` | 运行时产出与探针（截图/抓包/Chrome 临时 profile） |
| `/Lib/`、`/Scripts/`、`/include/`、`pyvenv.cfg`、`/.venv/` | 虚拟环境（Lib 352M / Scripts 6.4M） |
| `auth_cache/`、`**/auth_cache/`、`*.local.json` | 鉴权缓存与本地凭据（**含敏感信息**） |
| `*.pid` | 进程锁文件 |
| `*.bak_*` | 带时间戳的备份 |
| `/_myapp_trash_*/` | 代码清洁归档 |
| `/backend/app.db` | **误建的空 sqlite 占位**（真库是 `/db/app.db`） |
| `/backend/data/native_board_cache/` | 原生看板磁盘缓存（运行时可重建，单页可达数 MB） |
| `/backend/services/cn_ems/_pmcache/` | PM 性能数据下载缓存（19 万量级） |
| `/data/portal_profiles/_tmp_*/` | Chrome 临时 profile |
| `*-wal` / `*-shm` | SQLite 边车文件 |
| `/_tmp_*` | 根目录一次性探针脚本 |

> **注意 `backend\app.db` 是误建的空占位**，真库在 `db\app.db`。读错库会得到"空的但不报错"的结果。

## 五、关键文件地图

| 文件 | 作用 |
| --- | --- |
| `backend\main.py`（25KB） | FastAPI 入口、路由挂载、生命周期 |
| `backend\task_registry.py`（68KB） | **任务唯一登记处** `TASK_SPECS`（懒加载注册） |
| `backend\task_registry.md` | 任务注册表说明（字段、对外接口） |
| `backend\worker.py`（28KB） | 独立任务执行 worker |
| `backend\worker_watchdog.py`（32KB） | worker 看门狗（崩溃自动重拉） |
| `backend\backend_watchdog.py` | 后端看门狗 |
| `backend\WORKER.md` | worker 架构、容错设计、启停 |
| `backend\database.py`（17KB） | 数据访问层（`get_raw_connection` 等） |
| `backend\dialect_helpers.py` | SQLite/PG 方言适配 |
| `backend\services\` | 业务服务层（各数据源采集与计算） |
| `backend\routers\` | API 路由 |
| `backend\models\`、`schemas\` | ORM 模型与 Pydantic schema |
| `backend\.env`（不入库） | 运行配置，参照 `.env.example` |
| `frontend\src\App.tsx`（98KB） | 前端主入口与路由/菜单 |
| `frontend\src\i18n.tsx`（204KB） | 中英双字典 |
| `frontend\src\api.ts` | 前端 API 封装 |
| `frontend\src\theme.ts`、`index.css` | 主题与样式 |
| `frontend\src\pages\` | 各功能页（60+ 个 `.tsx`） |
| `frontend\scripts\generate-help-doc.mjs` | 帮助文档生成器 |
| `alembic\`、`alembic.ini` | 数据库迁移 |
| `tests\` | 测试 |

## 六、改数据层前必读（高破坏风险）

以下事实来自 `PROJECT_DOCS.md` §2 的全量稽核，**任何"统一改数据访问层"的改动都会静默坏图**：

1. **存在绕过 `get_raw_connection` 的裸 `sqlite3.connect`**，已知如 `ipran_chart_service.py:233`、`fw_kpi_services.py:488` —— 它们是**图表数据源**。
2. `get_raw_connection` 调用点实测约 **76 处**，不要假设能一次性替换。
3. `eflow_tt` 有**双库**（`app.db` 与 `eflow.sqlite3`）：同步任务**只写 `app.db`**；`eflow.sqlite3` 的副本是旧流水线遗留快照。
4. `db_ps_cs_cn` 的**真数据在远端**（经 HTTP `8765` 读），项目内同名文件是 **0 字节占位** —— 误当数据源会得到空结果而非报错。
5. 告警表 `realtime_alarm` / `history_alarm` 被**同时写** `app.db` 与 `eflow.sqlite3`，但**页面只读 `app.db`**。

> 现状**仍是 SQLite 为主**；SQLite→PostgreSQL 迁移是**规划定稿但未执行**（`PROJECT_DOCS.md` §2）。

## 七、进程与运维

生产不是"一个后端进程"：

```
uvicorn 后端 (:7038)
   ├── worker 分组进程（u / n / v / m / c …，各有 .pid）
   ├── worker_watchdog.py   —— worker 崩溃自动重拉
   └── backend_watchdog.py  —— 后端守护
```

- 启动：`start.bat` / `start_ensure.bat` / `start_hidden.ps1`（由看门狗托管 worker）
- 停止：`stop.bat`
- 巡检：`docs\manual\13-operations.md`（**五个关键进程是否都在**）
- 任务队列：SQLite `task_queue` 表（`pending/running/done/failed`），**不引入 Redis/RabbitMQ**；worker 串行执行，投递前查重防重复。

## 八、改代码前的检查清单

- [ ] 读了 `docs\manual\README.md` 的维护约定
- [ ] 新功能页：`App.tsx` + `i18n.tsx`（中英）+ `11-feature-guide.md` 三处同步
- [ ] 新任务：`TASK_SPECS` 已登记，且 `04-task-system.md` 已更新
- [ ] 前端产物目录仍是 `_fe_dist`
- [ ] 帮助内容改动后已重跑 `generate-help-doc.mjs`
- [ ] 没有新增裸 `sqlite3.connect`
- [ ] 没有把 `db\`、`log\`、`TMP\`、`auth_cache\`、`*.pid` 加进版本库
- [ ] 没有写敏感值
- [ ] 改大文件前建了 `_bak_<日期>_<说明>` 快照（本项目既有习惯）

## 九、本项目的 8 份体系文档

| # | 文件 | 内容 |
| --- | --- | --- |
| 01 | `AGENTS.md` | 本文 |
| 02 | `DESIGN.md` | 视觉规则 |
| 03 | `TODO.md` | 当前任务与优先级 |
| 04 | `project-overview.md` | 项目整体说明（指向手册） |
| 05 | `architecture.md` | 架构与数据流（指向手册） |
| 06 | `user-guide.md` | 面向使用者的说明（指向手册） |
| 07 | `development.md` | 开发方式、命令与回归清单 |
| 08 | `component-api.md` | 组件索引 |

> 均在 `Task\my_app\` 根目录（与 `PROJECT_DOCS.md` 同级）。
> **手册（`docs\manual\`）仍是详细内容的权威来源**，这 8 份负责"入口与约束"。

## 十、相关文档

| 内容 | 去哪里 |
| --- | --- |
| 工作区总纲 | `D:\01_RPA\AGENTS.md` |
| 手册导航 | `docs\manual\README.md` |
| 代码清理指南 | `docs\CODE_CLEANUP_GUIDE.md` |
| Excel 导出规范 | `docs\EXCEL_EXPORT_STANDARD.md` |
| FineBI 迁移 | `docs\FINEBI_MIGRATION.md` |
| 历史档案 | `PROJECT_DOCS.md`、`PROJECT_DOCS_ARCHIVE.md` |
| 统一门户 | `D:\01_RPA\liberia-noc_soc-数据看板统一门户\docs\AGENTS.md` |

> **工具负责整理，人与 AI 负责协作执行。**
