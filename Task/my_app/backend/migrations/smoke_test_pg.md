# Phase 6 PostgreSQL API 冒烟测试

## 目的

验证后端以 `MY_APP_DB_MODE=pg` 启动后，核心 API 与 PostgreSQL schema 均可用，
并确认 `/api/health`、`/api/db/info` 正确报告 PG 模式。

## 前置条件

- PostgreSQL 已启动，`backend\.env`（或项目根 `.env`）提供 `DATABASE_URL`。
- Phase 5 已迁移完成的 schema：`app`、`battery`、`ms_sla`、`ran_ume`、`ran_ume_ro`、`lte_pl`、`fw`、`eflow` 等。
- Python 解释器：`D:\01_RPA\Task\my_app\.venv-test\Scripts\python.exe`
  （依赖见 `smoke_requirements.txt`；`.venv-test` 使用 `include-system-site-packages`，
  若缺包可先 `pip install -r backend\migrations\smoke_requirements.txt`）。
- 端口 `7099` 空闲。

## 运行方式

在项目根目录执行：

```powershell
.\.venv-test\Scripts\python.exe backend\migrations\smoke_test_pg.py
```

可选环境变量：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `SMOKE_PG_PORT` | `7099` | uvicorn 端口 |
| `SMOKE_PG_START_TIMEOUT` | `60` | 等待端口/健康检查的秒数 |
| `MY_APP_PYTHON` | 自动探测 | 指定 Python 解释器 |

## 测试步骤

1. `py_compile` 校验 `database.py`、`main.py`、`routers/system.py`、`routers/alarm_dashboard.py` 等关键文件。
2. 读取 `backend\.env`（缺失回退根 `.env`）获取 `DATABASE_URL`，强制设置：
   - `MY_APP_DB_MODE=pg`（不修改 `.env`，仅进程内环境变量）
   - `MY_APP_DISABLE_SCHEDULER=1`（跳过 APScheduler 启动，避免后台任务干扰）
3. 后台启动 `uvicorn backend.main:app`（端口 7099，隐藏窗口）。
4. 等待端口就绪，并轮询 `/api/health` 至 200（超时 60s）。
5. 执行代表性 GET（每个路由器 2-3 个）：

| 路由器 | 检查项 |
| --- | --- |
| system | `/api/health`、`/api/db/info` |
| tt_wo_dashboard | `/api/tt-wo-dashboard/overview`、`/api/tt-wo-dashboard/drilldown` |
| alarm_dashboard | `/overview`、`/history-drilldown`、`/realtime-drilldown` |
| packet_loss_dashboard | `/overview`、`/map-sites`、`/drilldown` |
| battery_dashboard | `/all`、`/trend` |
| sp_dashboard | `/api/sp-data/summary`、`/api/warehouses`、`/api/data` |
| gis | `/api/gis/sites`、`/api/gis/regions/summary`、`/api/gis/topology` |
| tasks | `/api/tasks`、`/api/tasks/history`、`/api/eflow/status` |
| tables | `/api/tables`、`/api/tables/eflow_tt/data`、动态非空表 `/data` |

6. 直连 PG 校验：
   - `app.eflow_tt` 存在
   - `lte_pl.packet_loss_data` 存在
   - `battery.battery_reading` 存在
   - `ran_ume_ro` schema 存在
7. 关闭自启的 uvicorn，确认 7099 端口释放。

## 通过标准

- 所有检查项 PASS（HTTP 2xx 且 JSON 结构符合预期）。
- `/api/db/info` 中 `db_mode == "pg"`，且表清单包含
  `app.eflow_tt`、`lte_pl.packet_loss_data`、`battery.battery_reading`。
- 测试结束后无残留的 7099 监听进程。

## 失败排查

- 启动失败：查看脚本输出的 uvicorn 日志尾部，重点看 `DATABASE_URL` 连接、
  `MY_APP_DB_MODE` 是否被 `.env` 覆盖（本脚本强制为 `pg`）。
- 单接口 5xx：脚本会打印该接口的响应体；常见原因为 sqlite 方言 SQL 尚未
  兼容 PG（如 `CAST(... AS REAL)`、`datetime('now')`），可结合 PG 错误定位。
- `db_info` 缺少 schema 限定表：确认 `backend/database.py` 中 `_PsycopgRaw`
  的 `search_path` 包含对应 schema，且系统路由器 `db_info` 使用
  `information_schema.tables` 的 schema 限定逻辑。

## 文件清单

- `backend/migrations/smoke_test_pg.py`：冒烟脚本。
- `backend/migrations/smoke_test_pg.md`：本文档。
- `backend/migrations/smoke_requirements.txt`：运行依赖。

## 本阶段配套修复（Phase 6）

- `backend/database.py`：`MY_APP_DB_MODE` 优先读 OS 环境变量，`DATABASE_URL` 按
  `backend\.env` → 根 `.env` 回退；`_resolve_pg_schema` 补齐 `ran_ume_ro` 等映射；
  PG 原始游标返回同时支持 `row[0]` 与 `row["col"]` 的行对象，并避免无参 SQL
  经过 psycopg2 时被字面 `%` 误格式化。
- `backend/main.py`：新增 `MY_APP_DISABLE_SCHEDULER=1` 跳过 APScheduler 启动
  （冒烟/CI 模式），任务仍注册以便 `/api/tasks` 正常返回。
- `backend/routers/system.py`：`/api/health`、`/api/db/info` 报告 `db_mode`，
  PG 下 `db_info` 表清单使用 `schema.table` 限定名。
- `backend/routers/alarm_dashboard.py`：修复 `_history_metrics_sql` 变量错误与
  `assign_delay`（如 `900s`）在 PG 的类型转换；数值列不再用低精度 `AS REAL`。
- `backend/routers/tt_wo_dashboard.py`：站点关联/过滤统一 `CAST(... AS TEXT)`，
  兼容 PG 中 `site_id` 整数列与文本值比较。
- `backend/routers/packet_loss_dashboard.py`：列名含 `%` 的查询改为内联安全日期
  字面量；`datetime()` 改为 Python 计算；`LastDayMaxPL` 用双引号标识符。
- `backend/services/sp_dashboard.py`：`row["col"]` → 兼容双模索引；PG `date()`
  返回的日期对象统一转字符串；数值列判空使用 `CAST(... AS TEXT)`。
