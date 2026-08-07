"""task_queue: cross-process task queue table (Phase 3)

Revision ID: 0002_task_queue
Revises: 0001_baseline
Create Date: 2026-08-06

Phase 3 task scheduling decoupling: Web process enqueues tasks
(status=pending), independent Worker process (backend/worker.py)
claims and executes them, then writes back done/failed.

Production DB that has already been stamped at 0001_baseline should
run `alembic upgrade head` to create this table.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0002_task_queue'
down_revision: Union[str, None] = '0001_baseline'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'task_queue',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('task_id', sa.Text(), nullable=False),
        sa.Column('trigger_type', sa.Text(), nullable=False),
        sa.Column('status', sa.Text(), nullable=False),
        sa.Column('created_at', sa.Text(), nullable=False),
        sa.Column('started_at', sa.Text(), nullable=True),
        sa.Column('finished_at', sa.Text(), nullable=True),
        sa.Column('result_json', sa.Text(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_task_queue_status', 'task_queue', ['status'], unique=False)
    op.create_index('ix_task_queue_task_id', 'task_queue', ['task_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_task_queue_task_id', table_name='task_queue')
    op.drop_index('ix_task_queue_status', table_name='task_queue')
    op.drop_table('task_queue')
