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

  ⚠️ **同一层转换还有一个易踩的坑：SQL 字面量里的 `%` 必须转义或绕开。**

  psycopg2 把 `%` 当作参数占位符的起始符。`_qmark_to_pyformat` 只转 `?`，
  **不会**动字面量里的 `%`；于是任何 `LIKE '前缀%'` 写法在 PG 模式下都会抛：

  ```
  IndexError: list index out of range
  ```

  因为它把 `Closed%` 里的 `%` 当成了第 N 个参数位置，而 params 里没有那一项。
  SQLite 模式下不会报错（`?` 与 `%` 互不相干），所以**只有切到 PG 才暴露**，
  单测若只跑 SQLite 就发现不了。

  2026-10-18 实例：`tt_wo_dashboard.py` 的下钻状态分桶用了
  `t.status NOT LIKE 'Closed%'`，分桶结果**永远算不出来**；又因为外层是
  `except Exception: buckets = None`，异常被静默吞掉，「未闭环 N 个」这行
  悄悄消失、日志里一个字都没有（见 `d390f495` → 修复 `d074ed74`）。

  两种正确写法：

  ```python
  # ① 用函数避开 % —— 前缀比较推荐这个，语义最直白
  LEFT(t.status, 6) <> 'Closed'

  # ② 确实需要 LIKE 时，把 % 写成 %%（交给 psycopg 还原）
  t.status NOT LIKE 'Closed%%'
  ```

  **同时**：凡是把异常吞成"降级值"的地方，`except` 里必须留一行
  `logging.warning(..., exc_info=True)`。上面那个 bug 之所以潜伏，
  完全是被静默 `except` 藏住了——「不影响主结果」不等于「不需要留痕」。
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

`pg_to_sqlite_sync`（每小时 :45）把远程 PG 全库同步到本地 `db/app.db`，作为离线备份与回退快照（`task_registry.py:723`）。这意味着 `app.db` 里的业务表是**上一小时的镜像**，别在它上面做"实时"假设。

⚠️ **例外：`SKIP_TABLES` 里的"本地权威表"不是镜像**（`backend/scripts/sync_pg_to_sqlite.py:80`）。
`credentials`、`email_recipients`、`task_schedule_config` 由本机应用无条件写 SQLite，
同步任务一律跳过它们 —— 一旦被同步就会 `DROP TABLE` 重建，抹掉本地数据连带丢主键
（`credentials` 2026-09-18、`task_schedule_config` 2026-10-21 各踩过一次，判据与事故记录写在
该文件注释里）。判断一张表能不能进 `SKIP_TABLES`：**它的写入方是否与 DB 模式无关地固定写
SQLite**。`task_schedule_config` 尤其特殊：判定**只读本地这一份**，PG 那份是
`_save_schedule_config` 双写出来的**只写不读镜像**（细节见 `04-task-system.md` 的
「双库一致性：权威只有一份，PG 只是镜像」）。

## 迁移与建表：三套东西各司其职

| 位置 | 是什么 | 怎么用 |
| --- | --- | --- |
| 仓库根 `alembic/` | 真正的 Alembic 工程。`alembic.ini:7,9` 里的 `sqlite:///db/app.db` **只是占位**，真实 URL 由 `alembic/env.py:38-64` 按 `MY_APP_DB_MODE` 解析 | `alembic upgrade head`；回退 `alembic downgrade base` |
| `backend/migrations/` | **不是 Alembic**，是一次性数据搬迁/校验脚本（`transfer_*`、`reconcile`、`smoke_test_pg`） | 手工按需执行，不在正常发布流程里 |
| `backend/scripts/init_db.py` | 首次初始化建表 | 全新环境第一步 |

`alembic/versions/` 当前 6 个版本：`0001_baseline`（6 张结构表）、`0002_task_queue`、`0003`、`0004`、`5415704359dc_phase4_coverage`、`0005_tt_exclude_table`。

> `0005_tt_exclude_table`（2026-10-06）建 `app.tt_exclude` —— NUR 排除名单，由人工在数据浏览页上传维护（见 `11-feature-guide.md` 第 5 节）。
> 它是**结构表**（人工维护、列固定），因此走 Alembic；不要与「采集任务运行时自建」的动态表混为一谈。

**约定：动态 eFlow 表不进 migration**（`0001_baseline.py:13-15`）。这类表由采集任务在运行时按上游字段自行建表，因此 `alembic upgrade head` 之后表数量少于页面上看到的表数量是**正常现象**，不是迁移失败。

### ⚠️ 动态表的唯一约束从哪来（upsert 的隐含前提）

`dialect_helpers.upsert` 的 PG 分支生成 `INSERT ... ON CONFLICT (cols) DO UPDATE`，
**要求 `cols` 上真的存在主键或唯一索引**，否则 PG 直接报
`没有匹配 ON CONFLICT 说明的唯一或者排除约束`（2026-10-07 实测确认过该文案）。

SQLite 分支是 `INSERT OR REPLACE`，**不要冲突目标也照样工作**——所以
**只跑 SQLite 的测试永远发现不了这类缺陷**。这正是 2026-10-07 `tt_alarm` 线上故障
（`eflow_tt_whatsapp_alert_log` 老表无约束）能潜伏的原因。动态表加约束有两条路：

| 方式 | 代表 | 说明 |
| --- | --- | --- |
| **DDL 带约束**（推荐） | `ran_ume_network_kpi.py:964` 的 `PRIMARY KEY ("Begin Time","Group")` 写在 `CREATE TABLE` 里；`ms_sla_dashboard.py:80-98` 同理 | 新表天然正确。**但 `CREATE TABLE IF NOT EXISTS` 对已存在的表是 no-op**，不会给老表补约束 |
| **upsert 前显式建唯一索引** | `ipran_ume_kpi_service.py:998`、`mw_ume_kpi_service.py:848`、`ms_sla_sync.py:323`、`ran_ume_network_kpi.py`（PK 路径）、`sp_online_sync.py:433`、`sp_material_sync.py:273`、`sync_from_eflow_api.py:340` | 一律「**先删历史重复行 → DROP 旧同名索引 → CREATE UNIQUE INDEX**」，三件套缺一不可（`sp_material_sync.py:249` 写明：不先清重复行，`CREATE UNIQUE INDEX` 会直接报错） |
| **运行时补约束**（唯一一处） | `tt_alarm_store.py:186` 的 `_ensure_pk_constraint`，调用点 :304 | 全仓仅此一处「表已存在时补约束」的补丁式写法，因为线上表已经存在且无约束。属历史补救，**新代码不要模仿**，优先用 DDL 带约束 |

> **2026-10-07 全量核对结果**：对全部 15 个 upsert 目标表在 PG 实库上逐个执行
> `INSERT ... ON CONFLICT (冲突列) DO NOTHING`（`EXPLAIN`，事务内回滚，零数据改动），
> **15/15 全部通过**，无缺约束的表。涉及 `battery_trend`、`site_pl_summary`、
> `task_schedule_config`、`pl_meta`(在 `lte_pl` schema)、`eflow_tt_whatsapp_alert_log`、
> `portal_qc_snapshot`、`ms_sla_kpi`/`_wo`/`_meta`(在 `ms_sla_dashboard` schema)、
> `ran_ume` 的 4 张 `*_OLIB_Network_KPIs`、`sp_material`、`ume_in_customer_kpi`。
> 复现方式见下方"新增 upsert 目标前的自检"。

> **`ms_sla_*` 与 `pl_meta` 不在 `app` schema**：前者在 `ms_sla_dashboard`
> （由 `ms_sla_dashboard.py:113` 显式建 schema），后者在 `lte_pl`。
> **这两个 schema 都不在 search_path 上**，因此用
> `table_schema = ANY(current_schemas(false))` 这类查法会**误报"表不存在"**——
> 核对时请按表名全库扫描，别只查 search_path。

> **反过来的同一个坑：search_path 上有两份同名表时，裸名会串 schema（2026-10-15 事故）。**
> `realtime_alarm` 与 `history_alarm` 在 **`app` 和 `eflow` 两个 schema 各有一份**，
> 且**列口径完全不同** —— `app` 那份是全量（`realtime_alarm` 实测 149/150 列，
> 列名 snake_case，含 `tt_id` / `alarmraisedtime`，页面与任务读的就是它），
> `eflow` 那份是 `ALARM_COLUMNS` 过滤版（36 列，列名是 `TT ID` 这种原始风格，
> **没有** `alarmraisedtime`）。两条推论，都是这次定下来的硬规矩：
>
> 1. **写端的换表/建索引 DDL 必须带 schema 限定**。PG 的 `DROP TABLE` 会顺着
>    `search_path`（`app,eflow,lte_pl,…`，`backend/database.py:320`）逐级解析，
>    裸名 `DROP TABLE IF EXISTS "realtime_alarm"` 在 `eflow.realtime_alarm`
>    缺失时会**删掉 `app` 的那份**。`eflow_active_alarm` 每轮先写 eflow 副本再写
>    app 主库，两条裸名换名语句因此互相删对方的正式表，实测 `app.realtime_alarm`
>    每分钟消失约 0.14s。落地写法见 `eflow_alarm_service._conn_schema` /
>    `_swap_table_sql`，回归守卫 `tests/test_eflow_alarm_swap_schema.py`。
> 2. **读端判存在性/列集不要取 `ANY(current_schemas(false))` 并集**，会另一份
>    副本污染结论（本例表现为「表在、但 `tt_id`/`alarmraisedtime` 不在」）。
>    要哪份就限定哪份：`tt_alarm_trigger.TRIGGER_SCHEMA`（默认 `app`）就是这条规矩。
>
> **为什么 `eflow` 那份副本不能一删了之**：PG 模式下 `get_raw_connection(…eflow.sqlite3)`
> 返回的是 **eflow schema 的 PG 连接**，物理文件 `data/eflow/eflow.sqlite3`
> 自 2026-08-07 起就不再被写（446MB 冻结快照，直接开该文件的离线工具如
> `Task/eflow_Q&A/tools/gen_datadict.py` 读到的是它）；而一旦按熔断开关
> `MY_APP_DB_MODE=sqlite` 回退（回退方案 R7），`write_alarm_sqlite()` 又是
> 那份**真文件**的唯一生产者，且 `.19` 那台机器可能在 sqlite 模式下跑。
> 所以本次只修「串 schema」，不删双写 —— 删它是跨模式、跨主机的契约变更，需另行评估。

### 已知遗留：`ms_sla_sync` 索引创建失败的降级路径

`ms_sla_sync.py:308-327` 把「清重复行 + 建唯一索引」整段包在 `try` 里，
异常只记 `[SILENT-EXCEPT]` warning 并 `conn.rollback()`，**但没有清空 `pk_cols_db`**；
随后 `:342` 判断 `if pk_cols_db:` 仍为真，`:345` 照常调用
`upsert(..., conflict_cols=pk_cols_db)`。若索引因故没建成，这里会抛出
「没有匹配 ON CONFLICT 说明的唯一或者排除约束」，而**真正的原因（建索引失败）
已被上面的 except 吞掉**，排查时容易被误导。

触发条件苛刻（需要 `CREATE UNIQUE INDEX` 失败，而前置的清重复行已成功），
**当前线上未发生**，故未改动；改这个模块时应在 except 里同时置 `pk_cols_db = []`
把写入降级为纯 INSERT，与 `:301` 已有的降级写法保持一致。

### 新增 upsert 目标前的自检

写新的 `upsert(..., conflict_cols=[...])` 前，用这条 SQL 确认约束存在
（把 schema/表/冲突列替换掉）：

```sql
SELECT pg_get_constraintdef(c.oid)
FROM pg_constraint c
JOIN pg_class cl ON cl.oid = c.conrelid
JOIN pg_namespace n ON n.oid = cl.relnamespace
WHERE n.nspname = '<schema>' AND cl.relname = '<表>' AND c.contype IN ('p','u');
```

返回空就说明**缺约束**，要么在 `CREATE TABLE` 里补上，要么在 upsert 前按上表的
「三件套」显式建唯一索引。别只跑 SQLite 测试就认为没事。

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
2b. **新增 upsert 目标表时先确认冲突列上有唯一约束**（见"动态表的唯一约束从哪来"）——
    SQLite 下缺约束不报错，只有 PG 会拦，别让 SQLite 测试给你假绿；
3. 中文/长表名注意 63 字节截断；
4. 结构表变更走 Alembic，动态采集表不要塞进 migration；
5. 新库文件优先落到 `data/<任务名>/`，并在本页的"独立 SQLite"表格里补一行。
