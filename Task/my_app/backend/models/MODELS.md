# backend/models — ORM 模型总览（架构优化 Phase 2，2026-08-06）

本目录在 Phase 2 补全了全部数据表模型。按所属数据库分三类：

## 1. 主库 app.db（Base，参与 Alembic migration）

| 文件 | 模型 | 对应表 | 原建表位置 |
|---|---|---|---|
| analysis.py | AnalysisArchive | analysis_archive | scripts/init_db.py |
| analysis.py | UploadedFile | uploaded_files | main.py |
| task_schedule.py | TaskScheduleConfig | task_schedule_config | services/task_runner.py |
| task_execution.py | TaskExecutionLog | task_execution_log | services/task_runner.py |
| credential.py | Credential | credentials | services/credential_store.py |
| sp_sync.py | SpSyncLog | sp_sync_log | services/get_sp_table.py |
| task_queue.py | TaskQueue | task_queue | services/task_runner.py（Phase 3 跨进程任务队列） |

## 2. 独立库（各自 Base，不参与主库 Alembic）

| 文件 | Base | 数据库 | 表 |
|---|---|---|---|
| packet_loss.py | PlBase | lte_pl.sqlite3 | packet_loss_data（Core Table，无主键）/ site_pl_summary / pl_meta |
| battery.py | BatteryBase | battery_kpi.sqlite3 | battery_latest / battery_reading / battery_trend / battery_meta |

## 3. 动态表（automap 反射，无静态模型）

| 文件 | 覆盖表 | 原因 |
|---|---|---|
| eflow.py | eflow_tt / eflow_wo / eflow_cr / eflow_pm / eflow_site / eflow_person / realtime_alarm / history_alarm / _metadata | 列由 eFlow API 返回字段动态决定，会 ALTER ADD COLUMN |
| site.py | master_site_db / site_db / topology | 列随 Excel 导入模板变化 |

反射用法：
```python
from backend.models.eflow import get_eflow_classes
classes = get_eflow_classes()
tt = classes.get("eflow_tt")   # 表不存在时为 None
```

## Alembic 说明

- 配置：`my_app/alembic.ini` + `my_app/alembic/env.py`（URL 动态计算为绝对路径）
- baseline：`alembic/versions/0001_baseline.py`（6 张结构表）
- `alembic/versions/0002_task_queue.py`：Phase 3 新增 task_queue 表 + 2 个索引
- 生产库已执行 `alembic stamp head`（0001）后 `alembic upgrade head`（0002）
- 空库验证：设置环境变量 `MY_APP_DB_OVERRIDE=<测试库路径>` 后 `alembic upgrade head`
- 独立库与动态表不在 migration 管理范围（由各自服务建表）

## 依赖

见 models/requirements.txt（仅新增 alembic，SQLAlchemy 已在根 requirements）。
