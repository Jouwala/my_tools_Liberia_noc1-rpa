# routers/tasks.py — 任务管理 API

## 来源
架构优化 Phase 1（2026-08-06）从 `backend/main.py` 拆分而来。

## 端点清单

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/eflow/sync | 手动触发 eFlow 同步（旧兼容接口，受 require_protected 保护） |
| GET | /api/eflow/status | eFlow 同步状态（旧兼容接口） |
| GET | /api/tasks | 任务列表（含最新执行记录） |
| GET | /api/tasks/history | 全局执行历史 |
| GET | /api/tasks/failures | 近期失败聚类 |
| GET | /api/tasks/{task_id} | 任务详情 |
| POST | /api/tasks/{task_id}/run | 立即执行（受保护） |
| GET | /api/tasks/{task_id}/status | 是否运行中 |
| GET | /api/tasks/{task_id}/stats | 健康度统计 |
| GET | /api/tasks/{task_id}/history | 单任务执行历史 |
| POST | /api/tasks/{task_id}/schedule | 更新 cron |
| POST | /api/tasks/{task_id}/toggle | 启用/禁用 |

## 依赖
- `backend.services.task_runner`：调度框架核心
- `backend.task_registry.sync_history`：旧 eFlow 接口同步历史
- `backend.security.require_protected`：高危端点鉴权

无新增第三方依赖（fastapi 已在根 requirements.txt）。
