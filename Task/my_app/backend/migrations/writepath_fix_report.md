# Phase 6.5 写入路径修复报告（SQLite/PG 双模 upsert + 63 字节截断）

日期：2026-08-08 ｜ 范围：`backend/dialect_helpers.py`、`backend/services/ms_sla_sync.py`、`backend/services/ran_ume_network_kpi.py`、本报告

未修改：`backend/database.py`、`backend/services/ms_sla_report.py`、`backend/.env`（PG 连接串仅读取）；未做任何 git 操作；未启动 uvicorn；临时验证脚本 `tmp_verify_writepath_sqlite.py` / `tmp_verify_writepath_pg.py` 已运行完毕并删除。

## 1. 问题与根因

| # | 问题 | 根因 |
|---|---|---|
| 1 | `upsert()` 对含空格列名（`Begin Time` 等）在 sqlite 报 `near "Time": syntax error`，PG 同样必断 | 列名未加双引号直接拼 SQL；影响 ms_sla 12 表、ran_ume 4 表、eflow_tt（161 列，≥90 列全含空格） |
| 2 | PG 模式 `write_to_db` 对超 63 字节列名直接报错，同步任务失败 | PG 对**带引号**标识符超 `NAMEDATALEN-1` 是直接报错（不截断）；服务端用 `isinstance(conn, sqlite3.Connection)` 判断后仍按 sqlite 原名生成 CREATE TABLE / ALTER ADD COLUMN / INSERT |
| 3 | `except sqlite3.OperationalError` 捕不住 psycopg2 异常 | PG 连接/ALTER 失败会向上抛，任务失败 |
| 4 | （附带发现）psycopg2 带参数执行时，列名内的 `%`（如 `Cell Inter-RAT ...(% )`）被当作格式符 → `IndexError` | `_qmark_to_pyformat` 只转换 `?`，未处理标识符内的 `%`；本项目此前规避了"无参数时不格式化"，但带参数 INSERT 仍会触发 |
| 5 | （附带发现）`ran_ume_network_kpi.write_to_db` 连接重试用 `with get_raw_connection(...) as conn:` 并在块内 `break` | `get_raw_connection` 返回 `_ClosingConnection` / `_PsycopgRaw`，`with` 退出即 commit+close，后续 SQL 实际在已关闭连接上执行 |

## 2. 修改方案

### 2.1 backend/dialect_helpers.py

- 新增 `PG_MAX_IDENT = 63` 与 `pg_trunc_ident(name)`：UTF-8 编码后 ≤63 字节原样返回；>63 字节取前 63 字节，再 `.decode('utf-8', errors='ignore')` 丢弃尾部残缺多字节字符。
- 新增标识符/表名引用助手：
  - `_quote_ident`：普通双引号（用于 DDL 等**无参数** SQL）；
  - `pg_quote_ident`：双引号 + 内部 `%` 双写为 `%%`（仅用于**带参数** SQL，psycopg2 参数化时还原为 `%`）；
  - `_quote_table` / `_pg_quote_table`：支持 `schema.table` 按段处理，PG 每段先 63 字节截断。
- 重写 `upsert()`：
  - sqlite：`INSERT OR REPLACE INTO "t" ("c1", "c2", ...) VALUES (?, ...)`；
  - PG：列名先 `pg_trunc_ident` 再 `pg_quote_ident`，生成 `INSERT INTO ... ON CONFLICT ("pk") DO UPDATE SET "c"=EXCLUDED."c"`；
  - 冲突键覆盖全部列时退化为 `DO NOTHING`（避免 `DO UPDATE SET` 为空语法错误）；
  - 参数取值兼容"调用方传原始列名 / 已截断列名"两种字典键。
- `list_table_names` / `table_columns` / `safe_pragma` / `write_df` 语义未改。

### 2.2 backend/services/ms_sla_sync.py `write_to_db()`

- PG 分支：`db_headers = [pg_trunc_ident(h) for h in headers]`、`tname = pg_trunc_ident(table_name)`，CREATE TABLE / ALTER ADD COLUMN / 唯一索引 / records 字典键 / upsert / 无主键 INSERT 全部使用截断名；截断后重复列名告警。
- ALTER ADD COLUMN 包 `except Exception` + `[SILENT-EXCEPT]` 警告并继续（列已存在等场景不中断）。
- 无主键降级 INSERT 分支：PG 用 `pg_quote_ident`（`%` 转义）与截断表名。
- 末尾首列索引名 PG 侧同样 63 字节截断。

### 2.3 backend/services/ran_ume_network_kpi.py `write_to_db()`

- 同 ms_sla：`db_headers`/`tname` 截断，CREATE TABLE / ALTER ADD COLUMN / records / upsert 统一。
- 两处 `except sqlite3.OperationalError` → `except Exception` + `[SILENT-EXCEPT]`。
- 连接重试：`with ... as conn: ... break` 改为 `conn = get_raw_connection(...)`（修复提前关闭），重试捕获改为 `Exception`（兼容 psycopg2.OperationalError），并修复 `conn` 未定义时的 `close()` 引用。

### 2.4 backend/migrations/reconcile.py（只读复核，未改动）

- 行 48-50 `PG_MAX_IDENT = 63`，行 425-435 的映射逻辑 `c.encode("utf-8")[:63].decode("utf-8", errors="ignore")` 与新增 `pg_trunc_ident` 完全一致，无需修改。

## 3. 9 个超长列名（long_column_audit.md 第 5 节）

| # | 原始列名 | 字节数 | PG 实际列名（前 63 字节） |
|---|---|---:|---|
| 1 | Cell Inter-RAT PS Outgoing Handover Success Rate(WCDMA->GPRS)(%) | 64 | Cell Inter-RAT PS Outgoing Handover Success Rate(WCDMA->GPRS)(% |
| 2 | U31_3G & 3G+ Channel Elements Congestion Rate_901621_2_UROP.RNC-MO | 66 | U31_3G & 3G+ Channel Elements Congestion Rate_901621_2_UROP.RNC |
| 3 | U31_3G Call Setup Success Rate - R99 Data services_901596_2_UROP.RNC-MO | 71 | U31_3G Call Setup Success Rate - R99 Data services_901596_2_URO |
| 4 | U31_3G+ Call Setup Success Rate - HSDPA Data services_901597_2_UROP.RNC-MO | 74 | U31_3G+ Call Setup Success Rate - HSDPA Data services_901597_2_ |
| 5 | U31_3G+ Call Setup Success Rate – HSUPA Data services_901598_2_UROP.RNC-MO | 76 | U31_3G+ Call Setup Success Rate – HSUPA Data services_901598_ |
| 6 | U31_3G+ Drop Call Rate - HSDPA Data services_901604_2_UROP.RNC-MO | 65 | U31_3G+ Drop Call Rate - HSDPA Data services_901604_2_UROP.RNC- |
| 7 | U31_3G+ Drop Call Rate - HSUPA Data services_901605_2_UROP.RNC-MO | 65 | U31_3G+ Drop Call Rate - HSUPA Data services_901605_2_UROP.RNC- |
| 8 | U31_HSDPA Average Throughput per User_1552876397284-0-88_900005_2_UROP.RNC-MO | 77 | U31_HSDPA Average Throughput per User_1552876397284-0-88_900005 |
| 9 | U31_ZTE_Traffic of Downlink Data TBF (GByte)_901415_2_gv4.bsc-MO | 64 | U31_ZTE_Traffic of Downlink Data TBF (GByte)_901415_2_gv4.bsc-M |

注：列 6 与列 7 的截断结果仅最后一个字符不同（`-` 与 `O`），在本次 9 列集合内不冲突；生产 4 张 UMTS 表中两列并存，写入前已由代码做截断碰撞告警，若未来出现完全相同的 63 字节前缀需人工重命名。

## 4. 验证结果

### 4.1 py_compile

`python -m py_compile` 对 3 个修改文件 + 2 个临时脚本全部通过（`PY_COMPILE OK`）。

### 4.2 SQLite 验证（生产库只读；写操作仅在内存/临时副本）

| 验证项 | 结果 |
|---|---|
| `pg_trunc_ident` 63 字节边界（ASCII / 中文 21×3=63 / 22×3=66 / 62B+残缺汉字） | PASS |
| 含空格/引号/9 长列名的内存表 `INSERT OR REPLACE`（同主键两行 → 1 行，值被替换，schema 不变） | PASS |
| `db/app.db` 副本：38 张表逐表 upsert 1 行，schema 前后完全一致，0 语法错误 | PASS |
| ms_sla 库内存克隆：12 表全部 `INSERT OR REPLACE` 成功 | PASS |
| ran_ume 库内存克隆：4 表全部成功 | PASS |
| eflow 库内存克隆：8 表全部成功，eflow_tt = 161 列（≥90） | PASS |

### 4.3 PG 验证（连接串取自 backend/.env，全程单事务，最终 ROLLBACK）

目标：`postgresql://myapp:***@127.0.0.1:5432/myapp`（掩码）。

| 验证项 | 结果 |
|---|---|
| a) `dialect_helpers.upsert` 直连 ms_sla schema（限定名表，`ON CONFLICT ("pk") DO UPDATE SET`）：写 1 行 → 同主键再写 1 行 → 仍 1 行且值更新；information_schema 列名 = 63 字节截断名 | PASS |
| b) `ms_sla_sync.write_to_db`：`Begin Time` + 9 长列名建表/加列/唯一索引/upsert，information_schema.columns（schema=ms_sla）列名与 `pg_trunc_ident` 期望完全一致，1 行写入 | PASS |
| b) `ran_ume_network_kpi.write_to_db`：`Begin Time` + `Group` + 9 长列名建表/加列/主键冲突 upsert，information_schema.columns（schema=ran_ume）一致，1 行写入 | PASS |
| c) 回滚后 `to_regclass` 三个测试对象全为 NULL，information_schema 无任何残留列 | PASS |

### 4.4 PG 关键 SQL 示例（验证时捕获）

```sql
-- ms_sla 直连 upsert（列名已 63 字节截断 + 引号）
INSERT INTO "ms_sla"."zz_phase65_upsert"
  ("pk", "Begin Time", "U31_3G Call Setup Success Rate - R99 Data services_901596_2_URO")
VALUES (?, ?, ?)
ON CONFLICT ("pk") DO UPDATE SET
  "Begin Time"=EXCLUDED."Begin Time",
  "U31_3G Call Setup Success Rate - R99 Data services_901596_2_URO"=EXCLUDED."U31_3G Call Setup Success Rate - R99 Data services_901596_2_URO";

-- ms_sla write_to_db：建表 + 截断列（无参数 DDL，普通双引号）
CREATE TABLE IF NOT EXISTS "zz_phase65_ms_sla_verify" (
  "Begin Time" TEXT,
  "Cell Inter-RAT PS Outgoing Handover Success Rate(WCDMA->GPRS)(%" TEXT,
  ...);
CREATE UNIQUE INDEX "u_zz_phase65_ms_sla_verify"
  ON "zz_phase65_ms_sla_verify" ("Begin Time");

-- ran_ume write_to_db：建表 + 逐列 ALTER + 主键冲突 upsert
CREATE TABLE "zz_phase65_ran_ume_verify" (
  "Begin Time" TEXT NOT NULL,
  "Group" TEXT NOT NULL,
  PRIMARY KEY ("Begin Time", "Group"));
ALTER TABLE "zz_phase65_ran_ume_verify"
  ADD COLUMN "U31_3G+ Call Setup Success Rate - HSDPA Data services_901597_2_" TEXT;
INSERT INTO "zz_phase65_ran_ume_verify" ("Begin Time", "Group", ...)
VALUES (?, ?, ...)
ON CONFLICT ("Begin Time", "Group") DO UPDATE SET ...;
```

说明：带参数 INSERT 中，含 `%` 的截断列名以 `%%` 形式出现在 SQL 日志（如 `...GPRS)(%%`），psycopg2 参数化时还原为 `%`；无参数 DDL 保持单个 `%`。

## 5. 边界与后续提醒

1. `write_to_db` 在 PG 分支对**已存在**表只做"缺列补齐 + upsert"，不会重建表，与 Phase 5 搬运结果兼容（实际列名 = UTF-8 前 63 字节）。
2. `ON CONFLICT` 要求冲突列上存在唯一约束：ms_sla 由 `CREATE UNIQUE INDEX` 保证，ran_ume 由建表 `PRIMARY KEY` 保证；直连 `upsert()` 的调用方需自行保证。
3. 若未来出现两个超长列名截断为完全相同的前 63 字节，PG 会拒绝建第二列（或发生列冲突），代码已告警，需人工重命名后再同步。
4. 建议后续（不在本次范围）：`database.py` 的 `_qmark_to_pyformat` 可考虑统一转义 `%`，`ms_sla_report.py` 的 2 个硬编码长列名回退匹配仍属读路径风险项。
