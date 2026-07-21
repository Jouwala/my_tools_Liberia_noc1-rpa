"""数据库连接管理"""
import os
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import sessionmaker, declarative_base
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "db" / "app.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI依赖注入：获取数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_raw_connection():
    """获取原始SQLite连接（用于动态表查询）"""
    import sqlite3
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def list_tables():
    """列出所有用户表"""
    insp = inspect(engine)
    return [t for t in insp.get_table_names() if not t.startswith('sqlite_')]
