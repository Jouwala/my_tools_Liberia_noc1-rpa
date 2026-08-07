# Phase 5 Wave1 迁移脚本说明（battery / ms_sla / ran_ume）

## 用途

把三个 SQLite 源库按 schema 归口到 PostgreSQL：

| 域 | SQLite 源 | PG schema |
|---|---|---|
| battery | `data/battery/battery_kpi.sqlite3` | `battery` |
| ms_sla | `data/ms_sla/lbr_ms_sla_kpi.sqlite3` | `ms_sla` |
| ran_ume | `backend/services/ran_kpi_daily.sqlite3`（不可用时回退 `data/ran_ume/ran_kpi_daily.sqlite3`） | `ran_ume` |

只写上述三个 schema，不碰 `app` / `eflow` / `fw` / `lte_pl` / `public`，也不动
`credential_store`（鉴权库按 R8 硬排除）。

## 依赖

见同目录 `requirements.txt`：

- `pandas>=2.0.0`
- `psycopg2-binary==2.9.12`
- `sqlalchemy>=2.0.0`

PG 连接串读取顺序：环境变量 `DATABASE_URL`，否则 `backend/.env` 中的
`DATABASE_URL`。脚本不改 `backend/.env`，也不改 `MY_APP_DB_MODE`
（保持 `sqlite` 作为回退态）。

## 运行

```powershell
# 只读检查源库（不连 PG、不写入）
python backend/migrations/transfer_lane_a.py --dry-run

# 正式迁移（默认：先备份 -> 建 schema -> DROP+CREATE -> executemany 5000/批 -> 行数+MD5 对账）
python backend/migrations/transfer_lane_a.py

# 指定 ran_ume 用 data/ran_ume 版本（而非 backend/services 版本）
python backend/migrations/transfer_lane_a.py --ran-source data

# 只迁 battery，且用 pandas 分块
python backend/migrations/transfer_lane_a.py --only battery --method pandas
```

公共库单独使用：

```powershell
python backend/migrations/transfer_lib.py inspect <sqlite路径> [更多路径]
python backend/migrations/transfer_lib.py backup --root backup <sqlite路径> [更多路径]
```

## 迁移规则

1. **只读源**：SQLite 用 URI `mode=ro` 打开，全程不产生写锁、不改源文件。
2. **表清单**：`sqlite_master` 中 `type='table'` 且排除 `sqlite_%` 系统对象。
3. **DDL**：由 `PRAGMA table_info` 反推：
   - 先 `DROP TABLE IF EXISTS` 再 `CREATE TABLE`（R4 幂等，可重跑/DELETE 重导）；
   - 类型映射 `INTEGER -> BIGINT`、`REAL -> DOUBLE PRECISION`、
     `TEXT / BLOB / 其它 -> TEXT`；
   - 保留主键（复合主键按 `pk` 序号排序）；
   - schema / table / column 全部双引号转义，兼容 `2G_OLIB_Network_KPIs`、
     `Begin Time`、`[FDD]Call Setup Success Rate[SDR_ITBBU]`、含非断行空格等标识符。
4. **搬运**：默认 psycopg2 `executemany`，每 5000 行一提交；备选 pandas
   `read_sql_query(chunksize)` + `to_sql(method='multi')`。
5. **类型修正**：TEXT 列统一转 `str`（BLOB 按 latin-1 无损映射）；BIGINT /
   DOUBLE PRECISION 列严格解析，遇到非数值或非整型浮点立即报错，不静默截断。
6. **对账**：每表比较源/目标行数，并对全表做流式 MD5（同列序），任一不一致
   即退出码 1。

## R0 备份

正式迁移前默认把本次要迁的 sqlite（含 `-wal` / `-shm`）复制到
`backup/phase5_wave1_<YYYYmmdd_HHMMSS>/`，并把迁移+对账结果写为同目录
`report.json`。可用 `--skip-backup` 跳过（不推荐）。
