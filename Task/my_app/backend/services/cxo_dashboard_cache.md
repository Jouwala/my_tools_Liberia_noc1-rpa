# cxo_dashboard_cache.py — CXO 看板 last-known-good 缓存同步

## 用途

CXO Dashboard（`frontend/public/cxo_dashboard.html`）原本只有"内嵌静态快照 + 打开时实时拉取"两条数据链路，
VMAX / 代理不可用时静默退回过期快照，看板出现大片空数据。本服务补第三层：后台周期性拉全量接口，
按接口粒度维护 last-known-good 缓存（本次返回空/失败 → 保留旧值），前端打开时
"内嵌快照 → 缓存 → 实时"三层叠加，实时不可用也能显示最近可用数据。

## 运行方式

- **任务 ID**：`cxo_dashboard_cache_sync`（任务管理页可手动执行 / 调整 cron）
- **默认计划**：`*/10 * * * *`（每 10 分钟）
- **worker 分组**：`v` 组（2026-09-18 从 `n` 组拆出）。拆组理由：本任务与
  `vmax_cxo_daily_sync`、`vmax_multi_data_sync` 共用同一个 8790 VMAX 代理会话（门户 JSESSIONID
  单用户并发），彼此必须串行；但与 `n` 组的 eFlow/网管任务并无会话冲突，同组时反而被
  `sp_data_sync`（1.5~2h）这类长任务排在后面，导致 10 分钟级的缓存滞后一个多小时
- 注册位置：`backend/task_registry.py`（TASK_SPECS）+ `backend/worker_watchdog.py`（GROUP_TASK_MAP）
- **改注册表后必须重启 worker 进程树**（stop.bat → start.bat），旧 worker 内存里持旧任务清单

## 数据链路

```
worker(v组) → ensure_proxy(8790) → http://127.0.0.1:8790/proxy?url=<VMAX目标>
            → VMAX 门户 (10.123.255.12:26180, JSESSIONID 单会话, 代理内部自动 re-login)
```

与前端实时刷新共用同一个 8790 代理会话，不会新增门户登录（门户有单用户并发上限）。

## 产出文件

| 文件 | 说明 |
|---|---|
| `data/cxo_dashboard/last_known_good.json` | 缓存主文件，`GET /api/cxo-dashboard/cache` 透传给前端 |
| `data/cxo_dashboard/history.jsonl` | 每次运行追加一行 `{ts, overview_131..134, health_overall}` |

缓存结构：

```json
{
  "version": 1,
  "updated_at": "2026-09-02T20:00:00",
  "keys": {
    "service/Mobility/indicator/391": {"fetched_at": "...", "data_time": "...", "data": {原始响应}},
    "service/Mobility/map": {...}, "service/Mobility/delimit": {...}, "service/Mobility/limit": {...},
    "net/tab/1/indicator/391": {...}, "net/map": {...},
    "summary/trend_91": {...}, "summary/overview_131": {...},
    "summary/geMap": {...}, "summary/userData": {...}, "summary/cityUser": {...},
    "health/userExperience": {...}, "health/voiceService": {...}, "health/dataService": {...}
  }
}
```

## 空值判定（空值 → 保留旧缓存）

| 组件 | 判定 |
|---|---|
| indicator / map | `option.series` 任一 series 有 data / `option` 非空 |
| gemap (Summary) | 顶层 `series` 非空 |
| delimit | `isCauseAnalysis` 且 `option.series` 非空 |
| limit | `header` 且 `data` 非空数组 |
| overview | `kpiValue` 非 None |
| trend | `option.series` 或 `yData` 任一非空 |
| userData / cityUser | `option` 非空 |
| health UE | `value` 为非 0 数字，或任一子项 score 不是 `--`/`NA`/空 |
| health voice/data | `data` 非空数组 |

## 已知限制

- Health 页 VMAX 源头分区（`aggr_ds_cxo_score`）为空时实时/缓存都无数据，只能数据侧补分区；本方案保证"有过的数据不再丢"。
- 接口清单（业务/infoId/graphId）与 `cxo_dashboard.html` 的 `refreshInner` 逐字对齐，改看板接口时两侧同步。

## 依赖

见 `requirements_cxo_dashboard_cache.txt`（requests；其余为项目内模块 + 标准库）。
