"""分析归档模型"""
from sqlalchemy import Column, Integer, String, Text, DateTime, JSON
from sqlalchemy.sql import func
from backend.database import Base


class AnalysisArchive(Base):
    __tablename__ = "analysis_archive"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    description = Column(Text)
    table_name = Column(String(100))
    chart_config = Column(Text)  # JSON字符串：图表配置
    conclusions = Column(Text)   # 分析结论
    snapshot_data = Column(Text)  # JSON字符串：快照数据
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class UploadedFile(Base):
    __tablename__ = "uploaded_files"

    id = Column(Integer, primary_key=True, autoincrement=True)
    filename = Column(String(255), nullable=False)
    original_name = Column(String(255))
    table_name = Column(String(100))
    row_count = Column(Integer)
    col_count = Column(Integer)
    columns_info = Column(Text)  # JSON: 列信息
    quality_issues = Column(Text)  # JSON: 质量问题
    uploaded_at = Column(DateTime, server_default=func.now())
