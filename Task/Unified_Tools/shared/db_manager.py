"""
数据库连接管理模块
提供上下文管理器和连接池功能，确保数据库连接正确关闭
"""

import sqlite3
import threading
from contextlib import contextmanager
from functools import lru_cache
from typing import Optional

from .logger import get_logger

logger = get_logger('db_manager')


class DatabaseConnectionPool:
    """简单的数据库连接池"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._pools = {}
        return cls._instance

    def __init__(self):
        # 确保 _pools 属性存在
        if not hasattr(self, '_pools'):
            self._pools = {}

    def get_connection(self, db_path: str, timeout: float = 30.0):
        """
        从连接池获取或创建数据库连接

        Args:
            db_path: 数据库文件路径
            timeout: 连接超时时间（秒）

        Returns:
            sqlite3.Connection: 数据库连接对象
        """
        if db_path not in self._pools:
            with self._lock:
                if db_path not in self._pools:
                    self._pools[db_path] = []
                    logger.debug(f"创建新的连接池: {db_path}")

        if self._pools[db_path]:
            conn = self._pools[db_path].pop()
            try:
                conn.execute("SELECT 1")
                logger.debug(f"从连接池复用连接: {db_path}")
                return conn
            except sqlite3.Error as e:
                logger.warning(f"连接池中的连接已失效，创建新连接: {e}")
                try:
                    conn.close()
                except:
                    pass

        conn = sqlite3.connect(db_path, timeout=timeout)
        conn.row_factory = sqlite3.Row
        logger.debug(f"创建新的数据库连接: {db_path}")
        return conn

    def return_connection(self, db_path: str, conn: sqlite3.Connection):
        """
        将连接返回到连接池

        Args:
            db_path: 数据库文件路径
            conn: 数据库连接对象
        """
        if db_path in self._pools and conn:
            try:
                conn.execute("SELECT 1")
                self._pools[db_path].append(conn)
                logger.debug(f"连接返回到连接池: {db_path}")
            except sqlite3.Error:
                try:
                    conn.close()
                    logger.debug(f"连接已关闭: {db_path}")
                except:
                    pass

    def close_all(self, db_path: Optional[str] = None):
        """
        关闭所有连接或指定数据库的连接

        Args:
            db_path: 如果指定，只关闭该数据库的连接；否则关闭所有连接
        """
        if db_path:
            if db_path in self._pools:
                for conn in self._pools[db_path]:
                    try:
                        conn.close()
                    except:
                        pass
                self._pools[db_path].clear()
                logger.info(f"已关闭 {db_path} 的所有连接")
        else:
            for path, connections in self._pools.items():
                for conn in connections:
                    try:
                        conn.close()
                    except:
                        pass
                connections.clear()
            logger.info("已关闭所有数据库连接")


_connection_pool = DatabaseConnectionPool()


@contextmanager
def get_db_connection(db_path: str, timeout: float = 30.0):
    """
    数据库连接上下文管理器

    使用示例:
        with get_db_connection('database.db') as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM table")
            results = cursor.fetchall()

    Args:
        db_path: 数据库文件路径
        timeout: 连接超时时间（秒）

    Yields:
        sqlite3.Connection: 数据库连接对象
    """
    conn = None
    try:
        conn = _connection_pool.get_connection(db_path, timeout)
        yield conn
    except Exception as e:
        logger.error(f"数据库操作错误: {e}", exc_info=True)
        if conn:
            try:
                conn.rollback()
            except:
                pass
        raise
    finally:
        if conn:
            _connection_pool.return_connection(db_path, conn)


def close_all_connections(db_path: Optional[str] = None):
    """
    关闭所有数据库连接

    Args:
        db_path: 如果指定，只关闭该数据库的连接；否则关闭所有连接
    """
    _connection_pool.close_all(db_path)


@lru_cache(maxsize=32)
def check_db_exists(db_path: str) -> bool:
    """
    检查数据库文件是否存在（带缓存）

    Args:
        db_path: 数据库文件路径

    Returns:
        bool: 数据库是否存在
    """
    import os
    exists = os.path.exists(db_path)
    logger.debug(f"检查数据库存在性: {db_path} -> {exists}")
    return exists
