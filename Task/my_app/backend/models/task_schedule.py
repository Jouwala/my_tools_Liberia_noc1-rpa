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
    updated_at = Column(Text, nullable=False)
