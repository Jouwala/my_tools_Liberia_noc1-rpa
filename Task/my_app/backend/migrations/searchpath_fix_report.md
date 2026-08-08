# Phase 6.5 —— PG search_path 同名表歧义修复 + ms_sla_report 超长列名截断回退 验证报告

日期：2026-08-08 ｜ 性质：代码修复 + 只读验证（未改 backend/.env，未做任何 git 操作，PG 侧仅 SELECT）

## 1. 改动清单（仅白名单 2 文件）

### 1.1 backend/database.py

| 位置 | 改动 |
|---|---|
| `_resolve_pg_schema`（约 184 行） | 新增读写分离目录规则：父目录含 `ran_ume`（即 `data/ran_ume/*`）的路径 → `ran_ume_ro`。原因：读库 `data/ran_ume/ran_kpi_daily.sqlite3` 与写库 `backend/services/ran_kpi_daily.sqlite3` **stem 完全相同**（`ran_kpi_daily`），仅靠 stem 映射无法区分，必须按目录判别（与 migrations/reconcile.py DEFAULT_DOMAINS 的 ran_ume / ran_ume_ro 域定义一致）。其余映射表不变 |
| `_PsycopgRaw.__init__` | 新增 `search_path=None` 构造参数；为 None 时使用类级 `_SEARCH_PATH` 全局列表（原行为），其余调用方零改动兼容。docstring 同步更新 |
| `_pg_raw_connection` | 修复死代码：`target_schema = logical_name（显式优先）或 _resolve_pg_schema(db_path)`；每连接 `search_path = target_schema 置顶 + 全局列表其余项（去重保序）`，经新参数传入 `_PsycopgRaw` |

生效语义：
- 读 `data/ran_ume/*` → `ran_ume_ro,app,eflow,...,ran_ume,...,public`（读库优先）
- 写 `backend/services/ran_kpi_daily.sqlite3` → `ran_ume,...,ran_ume_ro,...,public`（写库优先）
- 默认 `db/app.db` → `app` 置顶；跨 schema 限定名查询不受影响（其余 schema 仍在路径中）
- sqlite 模式：`_pg_raw_connection` 只在 pg 模式被调，sqlite 分支代码零改动，逐字节兼容
- 现有 `logical_name` 调用方：ipran_chart_service（"ipran_ume"）置顶生效；fw_kpi_services 传的 "fw_db" 非 schema 名，PG 对 search_path 中不存在的 schema 静默忽略，fw 表仍经列表中 `fw` 项解析，行为无害

### 1.2 backend/services/ms_sla_report.py

`get_db_value()`（约 336 行）列存在性防护处新增截断回退（自包含 8 行，未 import reconcile）：
列名不在 `existing_cols` 且 UTF-8 编码 >63 字节时，取 `encode('utf-8')[:63].decode('utf-8', errors='ignore')` 截断名再匹配，命中则改用截断名拼 SQL。算法与 migrations/reconcile.py 的 `PG_MAX_IDENT=63` 回退完全一致。sqlite 模式列名原样存在，精确匹配先命中，回退天然不触发。

范围说明：按任务指令本次仅改 `get_db_value()`。**遗留**：`get_persite_ratio()`（约 387 行）有同样的列防护模式，PERSITE MAP 中的 901597/901604 两列（PS_CSSR_HSDPA / PS_DCR_HSDPA）在 PG 模式下仍会静默返回 None，建议后续以同款回退处理（本次指令未列入，未动）。

## 2. py_compile 结果

```
python -m py_compile backend/database.py backend/services/ms_sla_report.py
→ PY_COMPILE_OK（两文件均通过，无任何输出）
```

## 3. PG 模式 search_path 验证证据（MY_APP_DB_MODE=pg 环境注入，tmp_verify_searchpath.py，只读）

每路径一条 `SELECT current_schemas(false)` 实测：

| 路径 | current_schemas(false) | 断言结果 |
|---|---|---|
| a) 读库 `data/ran_ume/ran_kpi_daily.sqlite3` | `['ran_ume_ro','app','eflow','lte_pl','battery','ms_sla','fw','ipran_ume','ran_ume','public']` | PASS：ran_ume_ro@0 在 ran_ume@8 之前 |
| b) 写库 `backend/services/ran_kpi_daily.sqlite3` | `['ran_ume','app','eflow','lte_pl','battery','ms_sla','fw','ipran_ume','ran_ume_ro','public']` | PASS：ran_ume@0 在 ran_ume_ro@8 之前 |
| c) 默认 `db/app.db`（get_raw_connection 无参） | `['app','eflow','lte_pl','battery','ms_sla','fw','ipran_ume','ran_ume','ran_ume_ro','public']` | PASS：首项=app |

d) 同名表不带 schema 限定命中验证（读库连接，表 `3G_OLIB_Network_KPIs`）：
- `pg_tables` 按 current_schemas 顺序解析未限定表名 → 命中 schema=**ran_ume_ro**（PASS）
- information_schema 佐证同名表存在于 `['ran_ume','ran_ume_ro']` 两 schema
- `SELECT COUNT(*) FROM "3G_OLIB_Network_KPIs"`（未限定）=480 == `ran_ume_ro."3G_OLIB_Network_KPIs"` 限定直查=480（PASS）
- 写库连接同法解析 → 命中 schema=**ran_ume**（PASS）
- 说明：`to_regclass` 对 search_path 首项命中的关系会省略 schema 前缀（PG 原生行为），故命中 schema 用 pg_tables/current_schemas 顺序解析佐证
- 脚本耗时 0.41s，ALL PASS，已删除

## 4. get_db_value 截断回退验证证据（tmp_verify_truncate.py）

Part 1 sqlite 行为不变（内存库直连）：
- 完整长列名（901597，74B）精确命中 → value=0.9876（PASS，回退未触发）
- 短列名行为不变 → value=1.5（PASS）
- 不存在的超长列名（截断名也不存在）→ None（PASS）
- 无匹配日期 → None（PASS）

Part 2 PG 截断名映射（ms_sla 连接，current_schemas 首项=ms_sla，PASS）：
- information_schema.columns 对照：4 表（UMTS 1day/1month × NW/SITE）中 901597 列（74B→63B 截断为 `U31_3G+ Call Setup Success Rate - HSDPA Data services_901597_2_`）与 901604 列（65B→63B 截断为 `U31_3G+ Drop Call Rate - HSDPA Data services_901604_2_UROP.RNC-`）均存在，且原长名不存在（8 项 PASS）
- `get_db_value(conn, 'Hourly_KPI_RPA_SITE_MS_SLA_UMTS1day_NW', 原长名901597, '2026-06-18')` → **0.9976**（修复前此路径静默 None；PASS）
- 截断列 LIKE 直查同值 0.9976（PASS）
- 901604 取值 → **0.0022**（PASS）
- 虚构超长列名 → None（PASS）
- 脚本耗时 0.85s，ALL PASS，已删除

## 5. sqlite 模式兼容冒烟

默认模式（未设 MY_APP_DB_MODE）导入 backend.database + get_raw_connection() 读 app 库 sqlite_master 成功（0.29s）；`_resolve_pg_schema` 纯函数映射核查：`data/ran_ume/...→ran_ume_ro`、`backend/services/ran_kpi_daily.sqlite3→ran_ume`、`db/app.db→app`。

## 6. 红线遵守

- 仅改白名单文件 backend/database.py、backend/services/ms_sla_report.py（dialect_helpers.py / ms_sla_sync.py / ran_ume_network_kpi.py 未触碰，git status 中其改动来自另一 agent）
- backend/.env 未改；无 git 操作；PG 验证全只读；未启动 uvicorn；tmp_verify_* 脚本均已删除

## 7. 总耗时

验证脚本执行合计约 1.55s（0.41 + 0.85 + 0.29）；含前置阅读与改动在内的任务总耗时约 300s。
