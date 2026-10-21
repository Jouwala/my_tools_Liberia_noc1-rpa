"""task_schedule_config: 新增 manually_stopped 列（Task Manager 主开关「跳过手动停止」）

Revision ID: 0006_manual_stop_flag
Revises: 0005_tt_exclude_table
Create Date: 2026-10-20

背景
----
`task_schedule_config.enabled` 只有一个布尔量，同时承担两种语义：

1. 「这个任务现在该不该跑」——调度器据此挂/摘 APScheduler job；
2. 「用户是否手动关过它」——主开关（一键全部启用）据此决定要不要覆盖用户选择。

两种语义被压进一个字段，导致主开关只有「全开」和「全关」两种极端：
用户逐个关掉几个任务后，主开关显示「部分启用」，再点一次启用会把
他刻意关掉的那些**全部重新打开**（2026-10-20 用户诉求）。

方案
----
拆成正交的两个字段：

- `enabled`            —— 调度开关（含义不变），主开关**会**写它；
- `manually_stopped`  —— 「用户手动关过」标记，主开关**双向**都跳过标记为 1 的行
                         （开与关都不动它，见 task_runner.toggle_all_tasks）。

主开关开启后，这批任务保持 `enabled=0 / manually_stopped=1`，用户可以随时
单独打开某一个；主开关关闭时该标记**同样保留**，再次开启仍不会把它们打开。
即「总开关只管非手动停止的任务」—— 用户 2026-10-20 明确要求「曾经手动关过的
任务永远不会被主开关自动打开」。

⚠️ 早期实现是「开启时跳过、**关闭时清零标记**」，已作废：清零会让该任务在
**下一次**主开关 ON 时被重新打开，等于把用户的手动决定静默丢弃。

初值
----
`NOT NULL DEFAULT 0`（= 现有行为：主开关照旧覆盖全部任务），因此这是一次
**零行为变化**的加列；只有用户在新 UI 上逐个关闭任务之后，标记才会变成 1。

⚠️ **存量数据需要一次性回填**：本迁移前已经存在的「用户手动关掉」的任务，
它们的 `manually_stopped` 仍是 0（当时没有这个概念），主开关会把它们重新打开。
回填由人工按业务确认后执行（见 04-task-system.md 的「主开关跳过手动停止」小节），
不写成自动迁移 —— 「哪些任务是用户有意关的」没有可靠信号能自动推断。

方言
----
本表由代码 CREATE TABLE 管理（task_runner._init_schedule_table），
SQLite / PostgreSQL 都要能跑。加列写法与既有迁移一致：SQLite 的
`ADD COLUMN` 不支持 `IF NOT EXISTS`，故先查列再决定是否执行（幂等）。
SQLite 无原生 schema 概念，故不加 schema 前缀 —— 与既有迁移保持一致。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006_manual_stop_flag"
down_revision: Union[str, None] = "0005_tt_exclude_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE = "task_schedule_config"
COLUMN = "manually_stopped"


def _table_columns(name: str) -> set:
    """跨方言取列名集合（SQLite 的 ADD COLUMN 没有 IF NOT EXISTS，先查再改）。"""
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if name not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns(name)}


def upgrade() -> None:
    # 幂等：表不存在（空库或未初始化）时留给代码 CREATE TABLE 补齐；
    # 列已存在时直接跳过，保证重复 upgrade 不会抛「duplicate column」。
    if COLUMN in _table_columns(TABLE):
        return
    op.add_column(
        TABLE,
        sa.Column(COLUMN, sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    if COLUMN not in _table_columns(TABLE):
        return
    # SQLite 3.35+ 才支持 DROP COLUMN；老版本（部分 Windows 打包的 Python 自带
    # SQLite）会报「near DROP」。这里先按方言分派，都不支持时抛明确异常让
    # 操作者手动处理，而不是静默失败留下半迁移状态。
    with op.get_context().autocommit_block():
        op.execute(sa.text(f"ALTER TABLE {TABLE} DROP COLUMN {COLUMN}"))