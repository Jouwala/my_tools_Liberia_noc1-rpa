# -*- coding: utf-8 -*-
"""
统一缓存层（LRU + TTL + 前缀失效）

设计要点：
- 内存有限：最多 _MAX_ENTRIES 条，超出时驱逐最久未使用的（LRU）
- TTL 过期：条目超过 ttl_sec 秒后视为过期
- 前缀失效：invalidate(prefix) 可一键清除某类缓存
- 线程安全：使用 threading.Lock 保护
"""
import time
import threading
import logging
from collections import OrderedDict
from typing import Any, Optional, Callable

logger = logging.getLogger("cache")

_MAX_ENTRIES = 500        # 最大缓存条目数
_DEFAULT_TTL = 60         # 默认 TTL（秒）


class CacheEntry:
    __slots__ = ("value", "expires_at", "last_access")

    def __init__(self, value: Any, ttl: float):
        self.value = value
        self.expires_at = time.time() + ttl
        self.last_access = time.time()


class Cache:
    def __init__(self, max_entries: int = _MAX_ENTRIES, default_ttl: float = _DEFAULT_TTL):
        self._max_entries = max_entries
        self._default_ttl = default_ttl
        self._store: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        """获取缓存，命中返回 value，否则返回 None。"""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            if time.time() > entry.expires_at:
                # 已过期，删除
                del self._store[key]
                return None
            # 更新访问时间（LRU 用）
            entry.last_access = time.time()
            self._store.move_to_end(key)
            return entry.value

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        """设置缓存。"""
        with self._lock:
            ttl = ttl or self._default_ttl
            if key in self._store:
                self._store[key] = CacheEntry(value, ttl)
                self._store.move_to_end(key)
            else:
                # 容量检查：LRU 驱逐
                while len(self._store) >= self._max_entries:
                    self._store.popitem(last=False)
                self._store[key] = CacheEntry(value, ttl)

    def invalidate(self, prefix: str) -> int:
        """清除以 prefix 开头的所有缓存，返回清除数量。"""
        with self._lock:
            keys_to_delete = [k for k in self._store if k.startswith(prefix)]
            for k in keys_to_delete:
                del self._store[k]
            logger.debug("Cache invalidated %d entries with prefix '%s'", len(keys_to_delete), prefix)
            return len(keys_to_delete)

    def clear(self) -> int:
        """清空全部缓存。"""
        with self._lock:
            count = len(self._store)
            self._store.clear()
            return count

    def stats(self) -> dict:
        """返回缓存统计信息。"""
        with self._lock:
            now = time.time()
            alive = sum(1 for v in self._store.values() if now < v.expires_at)
            return {
                "total": len(self._store),
                "alive": alive,
                "expired": len(self._store) - alive,
                "max_entries": self._max_entries,
            }


# 全局单例
_instance: Optional[Cache] = None
_instance_lock = threading.Lock()


def get_cache() -> Cache:
    """获取全局缓存实例（单例）。"""
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = Cache()
        return _instance


def cached(key: str, ttl: Optional[float] = None, prefix: Optional[str] = None):
    """
    装饰器：缓存函数返回值。

    用法：
        @cached("overview|{start}|{end}", ttl=60)
        def get_overview(start, end):
            ...

        # 或使用 prefix 自动构建 key
        @cached(prefix="gis:meta")
        def get_meta():
            ...
    """
    def decorator(func: Callable) -> Callable:
        def wrapper(*args, **kwargs) -> Any:
            cache = get_cache()
            if prefix:
                cache_key = prefix
            else:
                cache_key = f"{key}|{args}|{tuple(sorted(kwargs.items()))}"
            result = cache.get(cache_key)
            if result is not None:
                return result
            result = func(*args, **kwargs)
            cache.set(cache_key, result, ttl)
            return result
        wrapper.__name__ = func.__name__
        return wrapper
    return decorator
