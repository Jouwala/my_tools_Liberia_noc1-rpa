# routers/sp_dashboard.py — SP 备件仓库看板 API

## 来源
架构优化 Phase 1（2026-08-06）从 `backend/main.py` 拆分而来。

## 端点清单

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/sp-data/summary | 各 SP 表概览（行数/列/同步时间/衍生指标） |
| GET | /api/sp-data/rows | 分页 + 模糊搜索某 SP 表数据 |
| GET | /api/data | 仓库看板主数据（对齐 Unified_Tools Flask /api/data） |
| GET | /api/warehouses | 仓库下拉列表 |
| GET | /api/details | 明细查询（inband/outband/inventory） |

## 依赖
- `backend.services.sp_dashboard`：看板计算逻辑（复用 app_sp_optimized.py）
- `backend.services.get_sp_table`：SP 表读取（懒加载）

无新增第三方依赖。
