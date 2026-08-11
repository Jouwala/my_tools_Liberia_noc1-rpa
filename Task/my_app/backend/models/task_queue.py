"""任务队列表模型（app.db）—— 架构优化 Phase 3

跨进程任务队列：Web 进程投递（status=pending），Worker 进程（backend/worker.py）
认领执行（running）并回写终态（done/failed）。
对应 task_runner._ensure_queue_table 的 CREATE TABLE IF NOT EXISTS task_queue。
"""
from sqlalchemy import Column, Integer, Text

from backend.database import Base


class TaskQueue(Base):
    __tablename__ = "task_queue"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(Text, nullable=False)
    trigger_type = Column(Text, nullable=False, default="manual")
    status = Column(Text, nullable=False, default="pending")  # pending/running/done/failed
    created_at = Column(Text, nullable=False)
    started_at = Column(Text)
    finished_at = Column(Text)
    result_json = Column(Text)
    error = Column(Text)
    worker_pid = Column(Integer)  # 认领并执行该队列记录的 Worker 进程 PID（停止执行功能用）
