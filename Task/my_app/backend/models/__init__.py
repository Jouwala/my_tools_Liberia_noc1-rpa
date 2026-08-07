# models module
# 架构优化 Phase 2（2026-08-06）：聚合注册全部模型，
# 确保 Base.metadata 包含所有 app.db 结构表（供 create_all / Alembic 使用）。
#
# 主库 app.db（Base）：
from backend.models.analysis import AnalysisArchive, UploadedFile  # noqa: F401
from backend.models.task_schedule import TaskScheduleConfig  # noqa: F401
from backend.models.task_execution import TaskExecutionLog  # noqa: F401
from backend.models.task_queue import TaskQueue  # noqa: F401 (Phase 3 跨进程任务队列)
from backend.models.credential import Credential  # noqa: F401
from backend.models.sp_sync import SpSyncLog  # noqa: F401

# 独立库（各自 Base，不参与主库 Alembic）：
#   models.packet_loss  -> lte_pl.sqlite3      (PlBase)
#   models.battery      -> battery_kpi.sqlite3 (BatteryBase)
# 动态表（automap 反射，无静态模型）：
#   models.eflow        -> eflow_* / realtime_alarm / history_alarm
#   models.site         -> master_site_db / topology
