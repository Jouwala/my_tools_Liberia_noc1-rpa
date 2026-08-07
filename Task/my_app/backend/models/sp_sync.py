"""SP 备件同步日志表模型（app.db）

对应原 backend/services/get_sp_table.py::_ensure_log_table 的
CREATE TABLE IF NOT EXISTS sp_sync_log。
"""
from sqlalchemy import Column, Integer, Text

from backend.database import Base


class SpSyncLog(Base):
    __tablename__ = "sp_sync_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    table_name = Column(Text)
    rows = Column(Integer)
    synced_at = Column(Text)
