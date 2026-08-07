"""Alembic 环境配置（Phase 4：双模 URL + 反向工程 autogenerate）

要点：
- target_metadata 默认绑定 backend.database.Base.metadata，
  并导入 backend.models 聚合模块以注册全部静态主库模型。
- sqlalchemy.url 按 MY_APP_DB_MODE 动态解析，不再硬编码：
    * sqlite（默认）：db/app.db 绝对路径；MY_APP_DB_OVERRIDE 可指向测试库。
    * pg：优先 MY_APP_DB_OVERRIDE（显式 URL），其次 backend/.env 的 DATABASE_URL。
- render_as_batch 仅 sqlite 启用（SQLite ALTER 兼容；PG 无需 batch 模式）。
- 反向工程模式（MY_APP_AUTOGEN_REFLECT=<存量 sqlite 文件>）：
    `alembic revision --autogenerate` 时从该文件反射受管表作为 target_metadata，
    用于把存量动态/Excel 导入表补成 migration；不设置该变量时行为与 Phase 2 一致。
    受管表范围：排除 eflow_* / _temp_* / sqlite_* / alembic_version，
    以及已由 0001/0002 静态模型管理的表。
"""
import os
import sys
from logging.config import fileConfig
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy import MetaData, Table, create_engine, engine_from_config, pool

from alembic import context

# 确保可以 import backend 包（my_app 根目录加入 sys.path）
MY_APP_ROOT = Path(__file__).resolve().parent.parent
if str(MY_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(MY_APP_ROOT))

from backend.database import Base, DB_PATH  # noqa: E402  （import 时已加载 backend/.env）
import backend.models  # noqa: E402,F401  注册全部静态主库模型到 Base.metadata

config = context.config


def _resolve_db_mode() -> str:
    mode = os.environ.get("MY_APP_DB_MODE", "sqlite").strip().lower()
    if mode not in ("sqlite", "pg"):
        raise RuntimeError(f"MY_APP_DB_MODE 必须为 sqlite|pg，收到: {mode!r}")
    return mode


def _resolve_url(mode: str) -> str:
    """按 DB_MODE 解析 sqlalchemy.url；不包含任何硬编码凭据。"""
    override = os.environ.get("MY_APP_DB_OVERRIDE", "").strip()
    if mode == "pg":
        if override:
            # 显式 URL 覆盖（如指向测试 PG）；优先于 backend/.env
            return override
        url = os.environ.get("DATABASE_URL", "").strip()
        if not url:
            raise RuntimeError(
                "DB_MODE=pg 但 DATABASE_URL 未设置（backend/.env 或环境变量）"
            )
        return url
    # sqlite：项目根目录下的 db/app.db 绝对路径；MY_APP_DB_OVERRIDE 可指向测试库
    target = Path(override).resolve() if override else DB_PATH
    return f"sqlite:///{target.as_posix()}"


DB_MODE = _resolve_db_mode()
DB_URL = _resolve_url(DB_MODE)
config.set_main_option("sqlalchemy.url", DB_URL)
RENDER_AS_BATCH = DB_MODE == "sqlite"
_AUTOGEN_REFLECT_SOURCE = os.environ.get("MY_APP_AUTOGEN_REFLECT", "").strip()
_STATIC_TABLE_NAMES = set(Base.metadata.tables.keys())


def _build_target_metadata():
    """默认使用静态 Base.metadata；反向工程模式下反射存量 sqlite 受管表。"""
    if not _AUTOGEN_REFLECT_SOURCE:
        return Base.metadata
    src = Path(_AUTOGEN_REFLECT_SOURCE).resolve()
    if not src.is_file():
        raise RuntimeError(f"MY_APP_AUTOGEN_REFLECT 指向的库不存在: {src}")
    source_engine = create_engine(f"sqlite:///{src.as_posix()}")
    meta = MetaData()
    with source_engine.connect() as conn:
        for name in sa.inspect(conn).get_table_names():
            if name.startswith(("eflow_", "_temp_", "sqlite_")) or name == "alembic_version":
                continue
            Table(name, meta, autoload_with=conn)
    return meta


target_metadata = _build_target_metadata()

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _include_object(obj, name, type_, reflected, compare_to) -> bool:
    """反向工程 autogenerate 时，跳过已由 0001/0002 静态模型管理的表及其索引，
    避免把存量库中已有、但模型反射范围之外的表误判为『应删除』。"""
    if not _AUTOGEN_REFLECT_SOURCE:
        return True
    if type_ == "table":
        return name not in _STATIC_TABLE_NAMES
    if type_ == "index":
        table = getattr(obj, "table", None)
        table_name = getattr(table, "name", None)
        if table_name is None and compare_to is not None:
            table_name = getattr(compare_to, "name", None)
        return table_name not in _STATIC_TABLE_NAMES
    return True


def run_migrations_offline() -> None:
    """离线模式：仅生成 SQL 脚本，不连接数据库。"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=RENDER_AS_BATCH,
        include_object=_include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：连接数据库执行 migration。"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=RENDER_AS_BATCH,
            include_object=_include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
