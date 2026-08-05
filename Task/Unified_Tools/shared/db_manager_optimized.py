
"""
优化版数据库连接管理模块
- 高性能连接池
- 线程安全
- 连接健康检查
- 自动重连机制
"""

import sqlite3
import threading
import time
from contextlib import contextmanager
from functools import lru_cache
from collections import deque

try:
    from .logger import get_logger
except ImportError:
    from logger import get_logger

logger = get_logger('db_manager_opt')


class PooledConnection:
    """包装的数据库连接，跟踪使用状态"""
    __slots__ = ('conn', 'created_at', 'last_used', 'in_use')

    def __init__(self, conn):
        self.conn = conn
        self.created_at = time.time()
        self.last_used = time.time()
        self.in_use = False


class DatabaseConnectionPool:
    """
    高性能数据库连接池
    - 固定大小连接池
    - 连接复用
    - 健康检查
    - 线程安全
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(DatabaseConnectionPool, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._pools = {}
        self._pool_locks = {}
        self._in_use_connections = {}
        self._max_pool_size = 10
        self._max_idle_time = 300.0
        self._connection_timeout = 30.0
        self._initialized = True
        logger.info("数据库连接池初始化完成")

    def configure(self, max_pool_size=10, max_idle_time=300.0, connection_timeout=30.0):
        """配置连接池参数"""
        with self._lock:
            self._max_pool_size = max_pool_size
            self._max_idle_time = max_idle_time
            self._connection_timeout = connection_timeout
            logger.info("连接池配置更新: max_size=%s, idle_time=%ss", max_pool_size, max_idle_time)

    def _get_pool_lock(self, db_path):
        """获取或创建数据库的锁"""
        if db_path not in self._pool_locks:
            with self._lock:
                if db_path not in self._pool_locks:
                    self._pool_locks[db_path] = threading.Lock()
        return self._pool_locks[db_path]

    def _create_connection(self, db_path):
        """创建新的数据库连接（只读模式）"""
        conn = sqlite3.connect(
            f"file:{db_path}?mode=ro",
            uri=True,
            timeout=self._connection_timeout,
            check_same_thread=False,
            isolation_level=None
        )
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError:
            pass
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-64000")
        conn.execute("PRAGMA temp_store=MEMORY")
        logger.debug("创建新数据库连接 (只读模式): %s", db_path)
        return conn

    def _is_connection_valid(self, conn):
        """检查连接是否有效"""
        try:
            conn.execute("SELECT 1")
            return True
        except sqlite3.Error:
            return False

    def _cleanup_idle_connections(self, db_path):
        """清理空闲超时的连接"""
        if db_path not in self._pools:
            return

        pool = self._pools[db_path]
        current_time = time.time()
        cleaned_count = 0

        new_pool = deque()
        while pool:
            pooled_conn = pool.popleft()
            if (current_time - pooled_conn.last_used < self._max_idle_time and
                self._is_connection_valid(pooled_conn.conn)):
                new_pool.append(pooled_conn)
            else:
                try:
                    pooled_conn.conn.close()
                    cleaned_count += 1
                except:
                    pass

        self._pools[db_path] = new_pool
        if cleaned_count > 0:
            logger.debug("清理了 %s 个空闲连接: %s", cleaned_count, db_path)

    def get_connection(self, db_path):
        """从连接池获取连接"""
        pool_lock = self._get_pool_lock(db_path)

        with pool_lock:
            if db_path not in self._pools:
                self._pools[db_path] = deque()
                self._in_use_connections[db_path] = 0

            pool = self._pools[db_path]
            self._cleanup_idle_connections(db_path)

            while pool:
                pooled_conn = pool.pop()
                if self._is_connection_valid(pooled_conn.conn):
                    pooled_conn.in_use = True
                    pooled_conn.last_used = time.time()
                    self._in_use_connections[db_path] += 1
                    logger.debug("从连接池获取连接: %s (使用中: %s)", db_path, self._in_use_connections[db_path])
                    return pooled_conn.conn

        conn = self._create_connection(db_path)
        with pool_lock:
            self._in_use_connections[db_path] = self._in_use_connections.get(db_path, 0) + 1
        return conn

    def return_connection(self, db_path, conn):
        """将连接返回到连接池"""
        if db_path not in self._pools:
            try:
                conn.close()
            except:
                pass
            return

        pool_lock = self._get_pool_lock(db_path)

        with pool_lock:
            pool = self._pools[db_path]
            in_use = self._in_use_connections.get(db_path, 0)

            if len(pool) < self._max_pool_size and self._is_connection_valid(conn):
                pooled_conn = PooledConnection(conn)
                pooled_conn.in_use = False
                pool.append(pooled_conn)
                logger.debug("连接返回到池: %s (池大小: %s)", db_path, len(pool))
            else:
                try:
                    conn.close()
                    logger.debug("连接已关闭（池已满）: %s", db_path)
                except:
                    pass

            if in_use > 0:
                self._in_use_connections[db_path] = in_use - 1

    def close_all(self, db_path=None):
        """关闭所有连接"""
        if db_path:
            pool_lock = self._get_pool_lock(db_path)
            with pool_lock:
                if db_path in self._pools:
                    for pooled_conn in self._pools[db_path]:
                        try:
                            pooled_conn.conn.close()
                        except:
                            pass
                    self._pools[db_path].clear()
                    self._in_use_connections[db_path] = 0
                    logger.info("已关闭 %s 的所有连接", db_path)
        else:
            for path in list(self._pools.keys()):
                self.close_all(path)


_connection_pool = DatabaseConnectionPool()


@contextmanager
def get_db_connection(db_path):
    """优化的数据库连接上下文管理器"""
    conn = None
    try:
        conn = _connection_pool.get_connection(db_path)
        yield conn
    except Exception as e:
        logger.error("数据库操作错误: %s", e, exc_info=True)
        if conn:
            try:
                conn.rollback()
            except:
                pass
        raise
    finally:
        if conn:
            _connection_pool.return_connection(db_path, conn)


def close_all_connections(db_path=None):
    """关闭所有连接"""
    _connection_pool.close_all(db_path)


def check_db_exists(db_path):
    """检查数据库是否存在"""
    import os
    return os.path.exists(db_path)
