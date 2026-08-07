"""凭据表模型（app.db）

对应原 backend/services/credential_store.py::_get_conn 的
CREATE TABLE IF NOT EXISTS credentials。
"""
from sqlalchemy import Column, Text

from backend.database import Base


class Credential(Base):
    __tablename__ = "credentials"

    key = Column(Text, primary_key=True)
    username = Column(Text)
    secret = Column(Text)
    updated_at = Column(Text)
