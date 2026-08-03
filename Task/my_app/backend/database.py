"""数据库连接管理"""
import logging
import os
import sqlite3
from sqlalchemy import create_engine, text, inspect, event
from sqlalchemy.orm import sessionmaker, declarative_base
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "db" / "app.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30},
    echo=False,
    pool_pre_ping=True,
)

# 统一所有连接的并发语义：写冲突时等待而非立刻报 "database is locked"。
# 仅设置每连接安全参数（busy_timeout 让写冲突等待，synchronous=NORMAL 提升性能）。
# 说明：WAL 模式虽能进一步解耦读写，但会在 -wal/-shm 文件上引入额外的并发/状态管理，
# 在长时间运行的服务里偶发 "closed database"；busy_timeout 已足以消除原始 locked 错误，
# 故此处不启用 WAL，改用更稳健的 rollback-journal + busy_timeout 方案。
def _set_sqlite_pragmas(dbapi_conn, connection_record):
    cur = dbapi_conn.cursor()
    try:
        cur.execute("PRAGMA busy_timeout=30000")
        cur.execute("PRAGMA synchronous=NORMAL")
    finally:
        cur.close()

event.listen(engine, "connect", _set_sqlite_pragmas)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI依赖注入：获取数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class _ClosingConnection(sqlite3.Connection):
    """带"退出即关闭"语义的 sqlite3 连接。

    ⚠️ 标准库陷阱：`with sqlite3.connect(...) as conn:` 是**事务**上下文管理器，
    退出时只 commit/rollback，**永远不会关闭连接**。因此单纯用 `with` 包裹
    并不能修复连接泄漏，这是本项目 "database is locked" 的根因之一。

    本子类重写 __exit__：先提交/回滚，再真正 close()。同时对"业务代码已在块内
    提前调用 conn.close()"的历史写法保持幂等，不再抛
    ProgrammingError: Cannot operate on a closed database。

    幂等实现：追踪 _closed 标志（覆盖 close()），__exit__ 若检测到连接已被块内
    提前关闭，则跳过 commit/rollback，直接走 finally 的 close()，避免对已关闭句柄
    调用 commit 触发 "closed database"。
    """

    _closed = False

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            super().close()
        except Exception:
            pass

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if not self._closed:
                if exc_type is None:
                    self.commit()
                else:
                    self.rollback()
        except Exception:  # noqa: BLE001 - 极小概率的提交期异常，幂等吞掉
            pass
        finally:
            self.close()
        return False  # 不吞原始异常


def get_raw_connection(db_path=None, timeout=30, check_same_thread=False):
    """获取原始SQLite连接（用于动态表查询 / 直接读写 db 文件）。

    已加固：busy_timeout=30000 + synchronous=NORMAL，避免并发写时的
    "database is locked"（写冲突时等待而非立刻报错）。返回的是
    _ClosingConnection，`with get_raw_connection() as conn:` 退出时会
    **提交并关闭**连接，异常路径同样保证释放。

    db_path: 可传入其它 db 文件路径；缺省使用项目主库 DB_PATH。
    """
    path = Path(db_path) if db_path is not None else DB_PATH
    conn = sqlite3.connect(
        str(path),
        timeout=timeout,
        check_same_thread=check_same_thread,
        factory=_ClosingConnection,
    )
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    try:
        # busy_timeout 让写冲突时等待而非立刻报 "database is locked"；
        # synchronous=NORMAL 在 rollback-journal 模式下提升写性能。
        cur.execute("PRAGMA busy_timeout=30000")
        cur.execute("PRAGMA synchronous=NORMAL")
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).warning("[SILENT-EXCEPT] get_raw_connection: exception swallowed", exc_info=True)
        pass
    finally:
        cur.close()
    return conn


def list_tables():
    """列出所有用户表"""
    insp = inspect(engine)
    return [t for t in insp.get_table_names() if not t.startswith('sqlite_')]
