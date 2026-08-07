"""Alembic 环境配置（架构优化 Phase 2）

要点：
- target_metadata 绑定 backend.database.Base.metadata，
  并导入 backend.models 聚合模块以注册全部主库模型。
- sqlalchemy.url 动态计算为绝对路径 db/app.db，避免相对路径歧义。
- 独立库（lte_pl.sqlite3 / battery_kpi.sqlite3）与动态表
  （eflow_* / master_site_db 等）不在本 migration 管理范围内。
"""
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

# 确保可以 import backend 包（my_app 根目录加入 sys.path）
MY_APP_ROOT = Path(__file__).resolve().parent.parent
if str(MY_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(MY_APP_ROOT))

from backend.database import Base, DB_PATH  # noqa: E402
import backend.models  # noqa: E402,F401  注册全部主库模型到 Base.metadata

config = context.config

# 动态覆盖数据库 URL 为绝对路径；
# 支持环境变量 MY_APP_DB_OVERRIDE 指向其它库文件（供空库验证/测试）
import os  # noqa: E402
_db_override = os.environ.get("MY_APP_DB_OVERRIDE", "").strip()
_db_url = Path(_db_override).resolve().as_posix() if _db_override else DB_PATH.as_posix()
config.set_main_option("sqlalchemy.url", f"sqlite:///{_db_url}")

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """离线模式：仅生成 SQL 脚本，不连接数据库。"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # SQLite ALTER 兼容性
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
            render_as_batch=True,  # SQLite ALTER 兼容性
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
