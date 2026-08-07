"""Packet Loss 丢包数据表模型（独立库 lte_pl.sqlite3，非 app.db）

对应原 backend/services/packet_loss_service.py::_init_db 的建表脚本。
使用独立 PlBase（与主库 Base 隔离），避免 Alembic 在主库误建这些表。
列名含空格/括号，全部用引号列名声明。
"""
from sqlalchemy import Column, Float, Index, Integer, Table, Text, UniqueConstraint
from sqlalchemy.orm import declarative_base

PlBase = declarative_base()


# packet_loss_data 无主键（以复合唯一约束充当业务键），无法 ORM 映射，
# 采用 Core Table 定义，查询用 select(packet_loss_data).where(...)。
packet_loss_data = Table(
    "packet_loss_data",
    PlBase.metadata,
    Column("Begin Time", Text, nullable=False),
    Column("End Time", Text),
    Column("Granularity", Text),
    Column("SubnetWork ID", Text),
    Column("SubnetWork Name", Text),
    Column("ManagedElement ID", Text),
    Column("Managed Element", Text),
    Column("dstIp", Text),
    Column("srcIp", Text),
    Column("Packet Loss Rate(%)", Float),
    Column("_sync_time", Text),
    UniqueConstraint("Begin Time", "ManagedElement ID", "srcIp", "dstIp"),
    Index("idx_pl_begin_time", "Begin Time"),
    Index("idx_pl_me", "Managed Element"),
)


class SitePlSummary(PlBase):
    __tablename__ = "site_pl_summary"

    site_name = Column("Site_Name", Text, primary_key=True)
    site_code = Column("Site_Code", Text)
    gateway = Column(Text)
    network_type = Column(Text)
    region = Column(Text)
    province_county = Column(Text)
    latitude = Column(Float)
    longitude = Column(Float)
    last_day_max_pl = Column("LastDayMaxPL", Float)
    total_pl = Column("TotalPL", Float)
    affected_hours = Column("AffectedHours", Integer)
    final_status = Column("FinalStatus", Text)
    updated_at = Column(Text)


class PlMeta(PlBase):
    __tablename__ = "pl_meta"

    key = Column(Text, primary_key=True)
    value = Column(Text)
