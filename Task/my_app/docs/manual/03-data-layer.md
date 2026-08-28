# 03 数据层设计

## 双模数据库：当前跑的是 PostgreSQL

`backend/database.py` 用一个开关切换两种后端：

| 开关 | 取值 | 行为 |
| --- | --- | --- |
| `MY_APP_DB_MODE` | `sqlite`（默认，`database.py:27`） | 走本地文件 `my_app/db/app.db`（`database.py:31`） |
| | `pg` | 走 `DATABASE_URL` 连接串（`database.py:34,37`），连接池由 `PG_POOL_SIZE`/`PG_MAX_OVERFLOW` 控制（:54-55） |

**`backend/.env` 当前实际是 `MY_APP_DB_MODE=pg`**，即远程 PostgreSQL 为主库，SQLite 作为回退熔断保留（`database.py:23-26`）。手册里所有"查库"操作都以此为准。

⚠️ 但 `db/app.db` 并没有因此变成死文件——它仍在被使用（见下方"例外"），当前体积约 954 MB，**不要当垃圾删除**。

## 方言适配层

跨方言的公共逻辑集中在两处，写新 SQL 前先确认这里有没有现成工具：

**`backend/database.py`**
- `_qmark_to_pyformat`（:215）：把代码里统一使用的 `?` 占位符转成 psycopg 的 `%s`。**因此新增查询请一律写 `?`，不要写 `%s` 或命名参数。**
- `_resolve_pg_schema`（:184）：把"SQLite 文件路径 + 表名"的历史调用映射到 PG 的 schema，兼容旧代码。
- `_PsycopgRaw`（:308）：给需要裸 DB-API 行为的代码提供 psycopg 连接包装。
- `_ClosingConnection`（:104-140）：修复连接泄漏，保证取到的连接最终被关闭。
- SQLite 侧 PRAGMA：`busy_timeout=30000`、`synchronous=NORMAL`（:76-89）——回退到 SQLite 时才不会 `database is locked`。

**`backend/dialect_helpers.py`（:73-168）**
- 表/列枚举、`safe_pragma`
- `upsert`：SQLite 用 `INSERT OR REPLACE`，PG 用 `ON CONFLICT`，一个函数两种行为
- `pg_trunc_ident`：PG 标识符按 63 字节截断（中文表名列名尤其容易踩）

## 例外：仍然硬绑 SQLite 的代码

`backend/services/credential_store.py:263-266` 用 `sqlite3` 直连 `db/app.db` 读写凭据表，**绕过 `MY_APP_DB_MODE`**。后果：

- PG 模式下凭据仍然存在本地 `app.db`，不随 PG 备份走；
- 只备份 PG 会丢凭据，只备份 `app.db` 会丢业务数据。备份策略见 `13-operations.md`。

同类"独立 SQLite"还有各任务的专用库，它们**从来不在主库里**：

| 文件 | 写入任务 | 消费方 |
| --- | --- | --- |
| `data/battery/battery_kpi.sqlite3` | `battery_kpi_sync`（每小时 :05） | 电池看板 |
| `data/packet_lost/lte_pl.sqlite3` | `packet_loss_sync`（每天 06:30） | 丢包看板（注意目录名是 `packet_lost`，不是 `packet_loss`） |
| `data/ms_sla/ms_sla_dashboard.sqlite3` | `ms_sla_full`（每 6 小时） | MS SLA 看板 |
| `data/ms_sla/lbr_ms_sla_kpi.sqlite3` | 同上流程的旧产物 | 旧库名，PROJECT_DOCS.md §7 引用的就是它；当前看板读 `ms_sla_dashboard.sqlite3` |

同目录下还有 `data/ran_ume/ran_kpi_daily.sqlite3`、`data/ipran_ume/ipran_ume_kpi.sqlite3`、`data/cnn_ume/`、`data/eflow/eflow.sqlite3`、`data/ran_kpi_avalability_1day.sqlite3` 等，命名沿用历史习惯（含 `avalability` 这类既有拼写错误），**不要顺手改名**——多处 SQL 与任务按字符串引用它们。

## PG → SQLite 快照

`pg_to_sqlite_sync`（每小时 :45）把远程 PG 全库同步到本地 `db/app.db`，作为离线备份与回退快照（`task_registry.py:332-337`）。这意味着 `app.db` 里的业务表是**上一小时的镜像**，别在它上面做"实时"假设。

## 迁移与建表：三套东西各司其职

| 位置 | 是什么 | 怎么用 |
| --- | --- | --- |
| 仓库根 `alembic/` | 真正的 Alembic 工程。`alembic.ini:7,9` 里的 `sqlite:///db/app.db` **只是占位**，真实 URL 由 `alembic/env.py:38-64` 按 `MY_APP_DB_MODE` 解析 | `alembic upgrade head`；回退 `alembic downgrade base` |
| `backend/migrations/` | **不是 Alembic**，是一次性数据搬迁/校验脚本（`transfer_*`、`reconcile`、`smoke_test_pg`） | 手工按需执行，不在正常发布流程里 |
| `backend/scripts/init_db.py` | 首次初始化建表 | 全新环境第一步 |

`alembic/versions/` 当前 5 个版本：`0001_baseline`（6 张结构表）、`0002_task_queue`、`0003`、`0004`、`5415704359dc_phase4_coverage`。

**约定：动态 eFlow 表不进 migration**（`0001_baseline.py:13-15`）。这类表由采集任务在运行时按上游字段自行建表，因此 `alembic upgrade head` 之后表数量少于页面上看到的表数量是**正常现象**，不是迁移失败。

## 运行时目录

| 目录 | 内容 | 备注 |
| --- | --- | --- |
| `db/` | `app.db`、`instance.lock`、`uploads/` | `instance.lock` 是单实例锁，异常退出残留时按 `13-operations.md` 处理 |
| `data/<任务名>/` | 各任务落盘产物（battery、eflow、ms_sla、ip_trace、incident_overview、finebi_reports…） | 报表文件的"最新版"来源页是任务报告文件页 |
| `backend/data/` | `settings.json`（目前仅 `remote_host`）、`sp/*.xlsx` 中间产物 | |
| `backend/services/auth_cache/` | 上游站点会话 cookie 缓存 | 由 `services/auth_manager.py:81` 维护，含有效凭据，**不得外发** |
| `data/app.db`、`data/my_app.db` | 0 字节的**历史路径遗留**（已实测根目录下没有同名文件） | 已不使用，可清理 |

## 给新功能作者的检查清单

1. 占位符统一写 `?`；
2. upsert 用 `dialect_helpers.upsert`，不要手写 `INSERT OR REPLACE`；
3. 中文/长表名注意 63 字节截断；
4. 结构表变更走 Alembic，动态采集表不要塞进 migration；
5. 新库文件优先落到 `data/<任务名>/`，并在本页的"独立 SQLite"表格里补一行。
