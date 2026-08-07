"""任务执行日志表模型（app.db）

对应原 backend/services/task_runner.py::_ensure_task_log_table 的
CREATE TABLE IF NOT EXISTS task_execution_log（含 error_trace 兼容补列）。
"""
from sqlalchemy import Column, Integer, Float, Text

from backend.database import Base


class TaskExecutionLog(Base):
    __tablename__ = "task_execution_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Text, nullable=False)
    task_name = Column(Text)
    category = Column(Text)
    trigger_type = Column(Text)
    success = Column(Integer)
    started_at = Column(Text)
    completed_at = Column(Text)
    elapsed_seconds = Column(Float)
    result_json = Column(Text)
    error = Column(Text)
    error_trace = Column(Text)
