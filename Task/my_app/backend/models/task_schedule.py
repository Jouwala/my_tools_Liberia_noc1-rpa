"""任务调度配置表模型（app.db）

对应原 backend/services/task_runner.py::_init_schedule_table 的
CREATE TABLE IF NOT EXISTS task_schedule_config。
"""
from sqlalchemy import Column, Integer, Text

from backend.database import Base


class TaskScheduleConfig(Base):
    __tablename__ = "task_schedule_config"

    task_id = Column(Text, primary_key=True)
    cron = Column(Text, nullable=False)
    enabled = Column(Integer, nullable=False, default=1)
    # 「用户手动关过」：与 enabled 正交。主开关重新启用时跳过标记为 1 的任务，
    # 从而做到「总开关控制全部非手动停止的任务」（2026-10-20）。
    # 与 alembic 0006_manual_stop_flag 的加列保持一致，两处都要改。
    manually_stopped = Column(Integer, nullable=False, default=0)
    updated_at = Column(Text, nullable=False)
