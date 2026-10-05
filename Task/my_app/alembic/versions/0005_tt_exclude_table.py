"""tt_exclude: NUR 排除名单落库（替代 FTP 实时拉取 xlsx）

Revision ID: 0005_tt_exclude_table
Revises: 0004_reflected_real_to_double
Create Date: 2026-10-06

背景
----
NUR 的「排除名单」原本由 `nur_calc._fetch_exclude_xlsx_bytes()` 每次去
FineBI 服务器 FTP 实时下载 `TT_Exclude.xlsx` 内存解析（不落盘、缓存 30 分钟）。
带来四个问题（2026-10-06 业务确认要落库）：

1. 名单是隐形的 —— 看板上只能看到条数与「拉取时间」，无人能查具体排除了哪些单；
2. 口径无法审计 —— xlsx 没有历史版本，无法回答「上週 NUR 为什么变了」；
3. **拉取时间 ≠ 内容时间** —— 标签显示的时间很新，内容却可能是几个月前的，
   用户会把「名单过时导致 NUR 全 0」误判成「计算算错了」（真实踩坑）；
4. 依赖 FTP 可用性 —— 拉取失败降级为空集时，NUR 口径会**静默变化**。

业务要求：**该名单由人工手动上传维护**（与 `vip_site_list` 那种「有上游文件、
可定时同步」的批量导入不同），上传即全量替换，并记录上传人与时间。

表结构
------
业务列只有票号一列（源文件实测 46 行 × 1 列，列名 `Ticket No.`）。
溯源列沿用本项目既有三件套（`tables.py:_attach_import_meta` 的
`_source_file` / `_source_sheet` / `_import_time`），另加 `_uploaded_by`
以满足多租户下「谁改了口径」的可追溯要求（AGENTS.md 三.4）。

双模
----
本迁移在 SQLite / PostgreSQL 下都能执行（项目要求两种方言都能跑，
见 Task/my_app/AGENTS.md 第六节）。SQLite 无原生 schema 概念，
故统一不加 schema 前缀 —— 与既有迁移保持一致（PG 侧由 search_path 落到 app）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0005_tt_exclude_table"
down_revision: Union[str, None] = "0004_reflected_real_to_double"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE = "tt_exclude"


def _table_exists(name: str) -> bool:
    """跨方言判断表是否存在（0004 用不到；这里幂等建表要用）。"""
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return name in insp.get_table_names()


def upgrade() -> None:
    if _table_exists(TABLE):
        return
    op.create_table(
        TABLE,
        # 票号是唯一业务键：同一单重复上传不产生重复行（全量替换 + 唯一约束双保险）
        sa.Column("ticket_no", sa.String(64), primary_key=True, nullable=False),
        # 溯源三件套：与 init_db / tables.py 的导入约定逐字一致，
        # 让「这张表的数据哪来的」在任何来源下都能回答
        sa.Column("_source_file", sa.String(255), nullable=True),
        sa.Column("_source_sheet", sa.String(255), nullable=True),
        sa.Column("_import_time", sa.String(64), nullable=True),
        # 人工上传特有：谁传的（口径变更的责任人）
        sa.Column("_uploaded_by", sa.String(128), nullable=True),
    )
    # 排序/审计用；票号本身已是主键，无需额外唯一索引
    op.execute(sa.text(
        f"CREATE INDEX IF NOT EXISTS idx_{TABLE}_import_time ON {TABLE} (_import_time)"
    ))


def downgrade() -> None:
    if not _table_exists(TABLE):
        return
    op.execute(sa.text(f"DROP INDEX IF EXISTS idx_{TABLE}_import_time"))
    op.drop_table(TABLE)
