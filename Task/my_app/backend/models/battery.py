"""电池 KPI 表模型（独立库 battery_kpi.sqlite3，非 app.db）

对应原 backend/services/battary_kpi_fetch/battery_kpi_service.py 的 DDL。
使用独立 BatteryBase（与主库 Base 隔离），避免 Alembic 在主库误建这些表。
"""
from sqlalchemy import Column, Float, Index, Integer, Text
from sqlalchemy.orm import declarative_base

BatteryBase = declarative_base()


class BatteryLatest(BatteryBase):
    __tablename__ = "battery_latest"
    __table_args__ = (
        Index("idx_latest_site", "site"),
        Index("idx_latest_fresh", "freshness"),
    )

    position = Column(Text, primary_key=True)
    mo = Column(Text)
    site = Column(Text)
    category = Column(Text)
    health = Column(Float)
    health_time = Column(Text)
    soc = Column(Float)
    soc_time = Column(Text)
    status = Column(Text)
    status_time = Column(Text)
    last_update = Column(Text)
    age_hours = Column(Float)
    freshness = Column(Text)
    snapshot_ts = Column(Text)


class BatteryReading(BatteryBase):
    __tablename__ = "battery_reading"
    __table_args__ = (
        Index("idx_reading_time", "reading_time"),
    )

    position = Column(Text, primary_key=True)
    reading_time = Column(Text, primary_key=True)
    site = Column(Text)
    category = Column(Text)
    health = Column(Float)
    soc = Column(Float)
    status = Column(Text)


class BatteryTrend(BatteryBase):
    __tablename__ = "battery_trend"

    snapshot_ts = Column(Text, primary_key=True)
    total = Column(Integer)
    sites = Column(Integer)
    fresh = Column(Integer)
    delayed = Column(Integer)
    stale = Column(Integer)
    no_data = Column(Integer)
    fresh_rate = Column(Float)
    avg_health = Column(Float)
    avg_soc = Column(Float)
    charging = Column(Integer)
    discharging = Column(Integer)
    unknown_status = Column(Integer)
    low_soc = Column(Integer)
    critical_soc = Column(Integer)
    degraded = Column(Integer)
    discharging_sites = Column(Integer)
    critical_sites = Column(Integer)


class BatteryMeta(BatteryBase):
    __tablename__ = "battery_meta"

    key = Column(Text, primary_key=True)
    value = Column(Text)
