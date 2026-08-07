# routers/system.py — 系统信息 API

## 来源
架构优化 Phase 1（2026-08-06）从 `backend/main.py` 拆分而来。

## 端点清单

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/health | 健康检查（数据库路径与存在性） |
| GET | /api/data-source/timestamps | eFlow 同步时间 + TT/WO 数据最新时间 |
| GET | /api/db/info | 数据库概览（表清单与行数） |

## 依赖
- `backend.database`：DB_PATH / get_raw_connection
- `backend.task_registry.sync_history`：内存同步历史

无新增第三方依赖。
