"""baseline: app.db 结构表初始定义（Phase 2）

Revision ID: 0001_baseline
Revises:
Create Date: 2026-08-06

覆盖 6 张由代码 CREATE TABLE 管理的结构表：
analysis_archive / uploaded_files / task_schedule_config /
task_execution_log / credentials / sp_sync_log。

已存在的生产库执行 `alembic stamp head` 标记即可，不重复建表；
空库执行 `alembic upgrade head` 可建出与生产一致的结构。

动态表（eflow_* / realtime_alarm / history_alarm / master_site_db /
topology / SP 备件数据表）由同步服务按 API 字段动态创建，
不在 migration 管理范围内。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0001_baseline'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'analysis_archive',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('table_name', sa.String(length=100), nullable=True),
        sa.Column('chart_config', sa.Text(), nullable=True),
        sa.Column('conclusions', sa.Text(), nullable=True),
        sa.Column('snapshot_data', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'uploaded_files',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('original_name', sa.String(length=255), nullable=True),
        sa.Column('table_name', sa.String(length=100), nullable=True),
        sa.Column('row_count', sa.Integer(), nullable=True),
        sa.Column('col_count', sa.Integer(), nullable=True),
        sa.Column('columns_info', sa.Text(), nullable=True),
        sa.Column('quality_issues', sa.Text(), nullable=True),
        sa.Column('uploaded_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'task_schedule_config',
        sa.Column('task_id', sa.Text(), nullable=False),
        sa.Column('cron', sa.Text(), nullable=False),
        sa.Column('enabled', sa.Integer(), nullable=False),
        sa.Column('updated_at', sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint('task_id'),
    )
    op.create_table(
        'task_execution_log',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('task_id', sa.Text(), nullable=False),
        sa.Column('task_name', sa.Text(), nullable=True),
        sa.Column('category', sa.Text(), nullable=True),
        sa.Column('trigger_type', sa.Text(), nullable=True),
        sa.Column('success', sa.Integer(), nullable=True),
        sa.Column('started_at', sa.Text(), nullable=True),
        sa.Column('completed_at', sa.Text(), nullable=True),
        sa.Column('elapsed_seconds', sa.Float(), nullable=True),
        sa.Column('result_json', sa.Text(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('error_trace', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'credentials',
        sa.Column('key', sa.Text(), nullable=False),
        sa.Column('username', sa.Text(), nullable=True),
        sa.Column('secret', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('key'),
    )
    op.create_table(
        'sp_sync_log',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('table_name', sa.Text(), nullable=True),
        sa.Column('rows', sa.Integer(), nullable=True),
        sa.Column('synced_at', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('sp_sync_log')
    op.drop_table('credentials')
    op.drop_table('task_execution_log')
    op.drop_table('task_schedule_config')
    op.drop_table('uploaded_files')
    op.drop_table('analysis_archive')
