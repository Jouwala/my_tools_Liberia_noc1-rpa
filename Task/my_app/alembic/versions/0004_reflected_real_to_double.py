"""reflected REAL columns: real -> double precision (PG only)

Revision ID: 0004_reflected_real_to_double
Revises: 0003_alarm_epoch_columns_bigint
Create Date: 2026-08-07

5415704359dc 从 SQLite 反射时把 REAL 列建成 PG `real`（单精度），
坐标/金额等数值会被舍入。Phase 5 Wave2 搬运前统一升为 double precision，
与 transfer_lib 的 `REAL -> DOUBLE PRECISION` 映射一致。SQLite 下跳过。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004_reflected_real_to_double"
down_revision: Union[str, None] = "0003_alarm_epoch_columns_bigint"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_REAL_COLUMNS = [
    ("flm_database", "col_2g_id"),
    ("flm_database", "col_3g_id"),
    ("flm_database", "col_4g_id"),
    ("flm_database", "latitude"),
    ("flm_database", "longitude"),
    ("flm_database", "col_4th_sector"),
    ("flm_database", "no_of_victims"),
    ("gateway_sites", "latitude"),
    ("gateway_sites", "longitude"),
    ("history_alarm", "auxiliarycount"),
    ("history_alarm", "assigned_time"),
    ("history_alarm", "match_count"),
    ("history_alarm", "latest_match_time"),
    ("history_alarm", "first_match_time"),
    ("history_alarm", "rootcount"),
    ("history_alarm", "assign_start_time"),
    ("inband_details", "Return Qty"),
    ("inband_details", "Material Manufacture"),
    ("inband_details", "Price"),
    ("inband_details", "EECN"),
    ("inband_details", "Revision"),
    ("inband_details", "PO Number"),
    ("inband_details", "Current Handler"),
    ("isp_sites", "site_id"),
    ("isp_sites", "latitude"),
    ("isp_sites", "longitude"),
    ("master_site_db", "latitude"),
    ("master_site_db", "longitude"),
    ("ocrule_details", "rulePriority"),
    ("outband_details", "Repair/Replace SLA"),
    ("outband_details", "Sub Domain"),
    ("outband_details", "Borrow Duration"),
    ("outband_details", "Specification"),
    ("outband_details", "Material Param"),
    ("outband_details", "Material Manufacture"),
    ("person", "address"),
    ("person", "nationality"),
    ("person", "phone_2"),
    ("person", "age"),
    ("person", "datasource"),
    ("person", "domain"),
    ("person", "sub_company"),
    ("person", "skill"),
    ("person", "exclude_dispach"),
    ("person", "sms_group"),
    ("person", "department"),
    ("person", "office"),
    ("person", "longitude"),
    ("person", "latitude"),
    ("person", "position"),
    ("person", "region_leader"),
    ("person", "skill1type"),
    ("person", "level1score"),
    ("person", "skill2type"),
    ("person", "level2score"),
    ("person", "skill3type"),
    ("person", "level3score"),
    ("realtime_alarm", "auxiliarycount"),
    ("realtime_alarm", "match_count"),
    ("realtime_alarm", "latest_match_time"),
    ("realtime_alarm", "first_match_time"),
    ("realtime_alarm", "assigned_time"),
    ("realtime_alarm", "assign_start_time"),
    ("special_sites", "latitude"),
    ("special_sites", "longitude"),
]


def _is_pg() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_pg():
        return
    for table, col in _REAL_COLUMNS:
        op.alter_column(
            table,
            col,
            existing_type=sa.REAL(),
            type_=sa.DOUBLE_PRECISION(),
            existing_nullable=True,
        )


def downgrade() -> None:
    if not _is_pg():
        return
    for table, col in _REAL_COLUMNS:
        op.alter_column(
            table,
            col,
            existing_type=sa.DOUBLE_PRECISION(),
            type_=sa.REAL(),
            existing_nullable=True,
        )
