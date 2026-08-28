# MS SLA 看板 API 说明

## 功能

`ms_sla_dashboard.py`（router）为 **MS Contract KPIs / MS WOs SLA** 数据看板提供后端
接口，数据源为 `data/ms_sla/ms_sla_dashboard.sqlite3`（由
`backend/services/ms_sla_dashboard.py` 在 `ms_sla_full` 任务中全量写入）。

## 接口

### GET /api/ms-sla-dashboard/overview

一次返回全部看板数据（TTL 缓存 60 秒）：

```json
{
  "meta": { "last_sync_time": "2026-08-12 17:35:00", "kpi_list_mtime": "...", "kpi_list_path": "..." },
  "nur":     { "daily": [{ "metric": "NUR_NETWORK", "2026-08-01": 0.00123, ... }], "monthly": [...] },
  "sla":     { "daily": [...], "monthly": [...] },
  "network": { "daily": [...], "monthly": [...] },
  "persite": { "daily": [...], "monthly": [...] },
  "wo":      { "daily": [{ "period": "2026-08-01", "metric": "TTR", "total": 10, "within_sla": 9, "achieve": 0.9 }], "monthly": [...] }
}
```

- `nur` / `sla` / `network` / `persite`：**指标为行、期间为列**的透视表结构
  （`metric` + 每个期间一列），与 NurDashboard 的 `NurRow[]` 对齐，便于前端
  表格与趋势图（echarts）直接复用。
- `wo`：明细行数组，`period` 为 `YYYY-MM-DD`（daily）或 `YYYY-MM`（monthly）；
  `achieve` 为达成率（0~1），低于目标标红（前端按 Excel 条件格式语义展示）。
- NUR 值为比率（0~1），前端展示 ×100000；SLA / network / persite 为百分比（0~1），
  前端展示 ×100。

## 容错

- 看板库不存在（首次部署、任务未运行）时返回空结构，前端展示"暂无数据"。
- 库内缺表时跳过对应数据集，不影响其它字段返回。

## 运行

后端启动后直接访问 `http://localhost:<port>/api/ms-sla-dashboard/overview`。

## 依赖

无新增第三方依赖（复用 FastAPI / sqlite3 / backend.database）。
