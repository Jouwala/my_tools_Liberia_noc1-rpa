
"""
智能缓存管理模块
- LRU缓存策略
- TTL过期机制
- 多级缓存
- 线程安全
"""

import time
import threading
import hashlib
from collections import OrderedDict
from functools import wraps

try:
    from .logger import get_logger
except ImportError:
    from logger import get_logger

logger = get_logger('cache_manager')
logger.setLevel(20)  # INFO level


class LRUCache:
    """
    线程安全的LRU缓存
    """

    def __init__(self, maxsize=1000, ttl=300.0):
        self._cache = OrderedDict()
        self._maxsize = maxsize
        self._ttl = ttl
        self._lock = threading.RLock()
        self._timestamps = {}

    def _evict_expired(self):
        """清理过期条目"""
        current_time = time.time()
        keys_to_delete = []

        for key in list(self._timestamps.keys()):
            if current_time - self._timestamps[key] > self._ttl:
                keys_to_delete.append(key)

        for key in keys_to_delete:
            if key in self._cache:
                del self._cache[key]
            if key in self._timestamps:
                del self._timestamps[key]

        if keys_to_delete:
            logger.debug("清理了 %s 个过期缓存项", len(keys_to_delete))

    def get(self, key):
        """获取缓存值"""
        with self._lock:
            self._evict_expired()
            if key not in self._cache:
                logger.debug("缓存未命中: %s", key)
                return None
            value = self._cache.pop(key)
            self._cache[key] = value
            self._timestamps[key] = time.time()
            logger.debug("缓存命中: %s", key)
            return value

    def set(self, key, value):
        """设置缓存值"""
        with self._lock:
            self._evict_expired()
            if key in self._cache:
                logger.debug("更新缓存: %s", key)
                self._cache.pop(key)
            elif len(self._cache) >= self._maxsize:
                evicted_key, _ = self._cache.popitem(last=False)
                logger.debug("缓存已满，驱逐最旧项: %s", evicted_key)
            self._cache[key] = value
            self._timestamps[key] = time.time()
            logger.debug("设置缓存: %s (当前缓存大小: %d/%d)", key, len(self._cache), self._maxsize)

    def clear(self):
        """清空缓存"""
        with self._lock:
            self._cache.clear()
            self._timestamps.clear()
            logger.info("缓存已清空")

    def __contains__(self, key):
        with self._lock:
            self._evict_expired()
            return key in self._cache

    def __len__(self):
        with self._lock:
            self._evict_expired()
            return len(self._cache)


class CacheManager:
    """
    多级缓存管理器
    - 内存缓存（LRU）
    - 查询结果缓存
    - 支持缓存预热
    - 支持命名空间隔离（线程安全）
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(CacheManager, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._query_cache = LRUCache(maxsize=500, ttl=60.0)
        self._data_cache = LRUCache(maxsize=200, ttl=300.0)
        self._stats_cache = LRUCache(maxsize=100, ttl=120.0)
        self._hit_count = 0
        self._miss_count = 0
        self._stats_lock = threading.Lock()
        self._namespace = threading.local()
        self._namespace.value = "default"
        self._initialized = True
        logger.info("缓存管理器初始化完成")

    def set_namespace(self, namespace):
        """设置当前线程的缓存命名空间"""
        self._namespace.value = namespace
        logger.info("缓存命名空间设置为: %s (线程: %s)", namespace, threading.current_thread().name)

    def get_namespace(self):
        """获取当前线程的缓存命名空间"""
        return getattr(self._namespace, 'value', 'default')

    def _make_key(self, *args, **kwargs):
        """生成缓存键（包含命名空间）"""
        namespace = self.get_namespace()
        key_parts = [namespace]
        key_parts.extend(str(arg) for arg in args)
        key_parts.extend("%s=%s" % (k, v) for k, v in sorted(kwargs.items()))
        key_str = "|".join(key_parts)
        key = hashlib.md5(key_str.encode()).hexdigest()
        logger.debug("生成缓存键: %s (命名空间: %s, 原始: %s)", key, namespace, key_str)
        return key

    def _record_hit(self):
        with self._stats_lock:
            self._hit_count += 1

    def _record_miss(self):
        with self._stats_lock:
            self._miss_count += 1

    def get_stats(self):
        """获取缓存统计"""
        with self._stats_lock:
            total = self._hit_count + self._miss_count
            hit_rate = self._hit_count / total if total > 0 else 0.0
            return self._hit_count, self._miss_count, hit_rate

    def cached_query(self, ttl=None):
        """
        数据库查询缓存装饰器
        """
        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                key = self._make_key(func.__name__, *args, **kwargs)
                cached = self._query_cache.get(key)
                if cached is not None:
                    self._record_hit()
                    logger.debug("查询缓存命中: %s", func.__name__)
                    return cached
                self._record_miss()
                result = func(*args, **kwargs)
                self._query_cache.set(key, result)
                return result
            return wrapper
        return decorator

    def cached_data(self, ttl=None):
        """
        数据缓存装饰器
        """
        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                key = self._make_key(func.__name__, *args, **kwargs)
                cached = self._data_cache.get(key)
                if cached is not None:
                    self._record_hit()
                    logger.debug("数据缓存命中: %s", func.__name__)
                    return cached
                self._record_miss()
                result = func(*args, **kwargs)
                self._data_cache.set(key, result)
                return result
            return wrapper
        return decorator

    def cached_stats(self, ttl=None):
        """
        统计数据缓存装饰器
        """
        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                key = self._make_key(func.__name__, *args, **kwargs)
                cached = self._stats_cache.get(key)
                if cached is not None:
                    self._record_hit()
                    logger.debug("统计缓存命中: %s", func.__name__)
                    return cached
                self._record_miss()
                result = func(*args, **kwargs)
                self._stats_cache.set(key, result)
                return result
            return wrapper
        return decorator

    def invalidate_query_cache(self, pattern=None):
        """
        使查询缓存失效
        """
        self._query_cache.clear()
        logger.info("查询缓存已失效")

    def invalidate_all(self):
        """
        使所有缓存失效
        """
        self._query_cache.clear()
        self._data_cache.clear()
        self._stats_cache.clear()
        logger.info("所有缓存已失效")

    def print_stats(self):
        """打印缓存统计信息"""
        hits, misses, hit_rate = self.get_stats()
        logger.info("缓存统计: 命中=%s, 未命中=%s, 命中率=%.2f%%", hits, misses, hit_rate * 100)


_cache_manager = CacheManager()


def get_cache_manager():
    """获取缓存管理器单例"""
    return _cache_manager

