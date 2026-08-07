"""alarm epoch columns: integer -> bigint (PG only)

Revision ID: 0003_alarm_epoch_columns_bigint
Revises: 5415704359dc
Create Date: 2026-08-07

history_alarm / realtime_alarm 的毫秒级时间戳和 id 在 SQLite 中声明为 INTEGER，
但实际值（epoch millis）超过 PG integer 的 2^31 上限。Phase 5 Wave2 搬运前
把这些列升为 BIGINT。SQLite 下无此问题，迁移直接跳过。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003_alarm_epoch_columns_bigint"
down_revision: Union[str, None] = "5415704359dc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_COLUMNS = {
    "history_alarm": [
        "historyservertime",
        "alarmchangedtime",
        "id",
        "offsetalarmraisedtime",
        "alarmraisedtime",
        "acktime",
        "servertime",
        "offsetalarmclearedtime",
        "alarmclearedtime",
        "clearservertime",
    ],
    "realtime_alarm": [
        "alarmchangedtime",
        "id",
        "offsetalarmraisedtime",
        "alarmraisedtime",
        "servertime",
    ],
}


def _is_pg() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_pg():
        return
    for table, cols in _COLUMNS.items():
        for col in cols:
            op.alter_column(
                table,
                col,
                existing_type=sa.INTEGER(),
                type_=sa.BIGINT(),
                existing_nullable=True,
            )


def downgrade() -> None:
    if not _is_pg():
        return
    for table, cols in _COLUMNS.items():
        for col in cols:
            op.alter_column(
                table,
                col,
                existing_type=sa.BIGINT(),
                type_=sa.INTEGER(),
                existing_nullable=True,
            )
