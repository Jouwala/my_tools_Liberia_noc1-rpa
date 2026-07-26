

"""
性能监控模块
- 函数执行时间统计
- 内存使用监控
- CPU使用率追踪
- 性能报告生成
"""

import time
import threading
import functools
from collections import defaultdict
from datetime import datetime

try:
    from .logger import get_logger
except ImportError:
    from logger import get_logger

logger = get_logger('perf_monitor')


class PerformanceMetrics:
    """性能指标数据类"""
    def __init__(self):
        self.call_count = 0
        self.total_time = 0.0
        self.min_time = float('inf')
        self.max_time = 0.0
        self.avg_time = 0.0
        self.last_call_time = 0.0
        self.memory_samples = []

    def update(self, execution_time):
        """更新性能指标"""
        self.call_count += 1
        self.total_time += execution_time
        self.min_time = min(self.min_time, execution_time)
        self.max_time = max(self.max_time, execution_time)
        self.avg_time = self.total_time / self.call_count
        self.last_call_time = time.time()


class PerformanceMonitor:
    """
    性能监控器
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(PerformanceMonitor, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._metrics = defaultdict(PerformanceMetrics)
        self._enabled = True
        self._start_time = time.time()
        self._initialized = True
        logger.info("性能监控器初始化完成")

    def enable(self):
        """启用监控"""
        self._enabled = True
        logger.info("性能监控已启用")

    def disable(self):
        """禁用监控"""
        self._enabled = False
        logger.info("性能监控已禁用")

    def record_execution(self, func_name, execution_time):
        """记录函数执行时间"""
        if not self._enabled:
            return
        with self._lock:
            self._metrics[func_name].update(execution_time)

    def timed(self, func=None, name=None):
        """
        性能监控装饰器
        """
        def decorator(f):
            func_identifier = name or f.__name__

            @functools.wraps(f)
            def wrapper(*args, **kwargs):
                if not self._enabled:
                    return f(*args, **kwargs)

                start_time = time.perf_counter()
                try:
                    return f(*args, **kwargs)
                finally:
                    execution_time = time.perf_counter() - start_time
                    self.record_execution(func_identifier, execution_time)

            return wrapper

        if func is not None:
            return decorator(func)
        return decorator

    def get_metrics(self, func_name=None):
        """获取性能指标"""
        with self._lock:
            if func_name:
                if func_name not in self._metrics:
                    return {}
                m = self._metrics[func_name]
                return {
                    'call_count': m.call_count,
                    'total_time': m.total_time,
                    'min_time': m.min_time,
                    'max_time': m.max_time,
                    'avg_time': m.avg_time,
                    'last_call_time': m.last_call_time
                }
            return {
                name: {
                    'call_count': m.call_count,
                    'total_time': m.total_time,
                    'min_time': m.min_time,
                    'max_time': m.max_time,
                    'avg_time': m.avg_time
                }
                for name, m in self._metrics.items()
            }

    def get_summary(self):
        """获取性能摘要"""
        with self._lock:
            total_calls = sum(m.call_count for m in self._metrics.values())
            total_time = sum(m.total_time for m in self._metrics.values())
            uptime = time.time() - self._start_time

            return {
                'uptime_seconds': uptime,
                'total_function_calls': total_calls,
                'total_execution_time': total_time,
                'monitored_functions': len(self._metrics),
                'avg_calls_per_second': total_calls / uptime if uptime > 0 else 0
            }

    def print_report(self):
        """打印性能报告"""
        summary = self.get_summary()
        metrics = self.get_metrics()

        logger.info("=" * 80)
        logger.info("性能监控报告")
        logger.info("=" * 80)
        logger.info("运行时间: %.2fs", summary['uptime_seconds'])
        logger.info("总调用次数: %s", summary['total_function_calls'])
        logger.info("总执行时间: %.4fs", summary['total_execution_time'])
        logger.info("监控函数数: %s", summary['monitored_functions'])
        logger.info("平均调用频率: %.2f/s", summary['avg_calls_per_second'])
        logger.info("")

        if metrics:
            logger.info("函数性能详情:")
            logger.info("%-40s %-10s %-12s %-10s %-10s %-10s", 
                       "函数名", "调用次数", "总时间(ms)", "平均(ms)", "最小(ms)", "最大(ms)")
            logger.info("-" * 100)

            for name, data in sorted(metrics.items(), key=lambda x: -x[1]['total_time']):
                logger.info(
                    "%-40s %-10s %-12.2f %-10.2f %-10.2f %-10.2f",
                    name,
                    data['call_count'],
                    data['total_time'] * 1000,
                    data['avg_time'] * 1000,
                    data['min_time'] * 1000,
                    data['max_time'] * 1000
                )
        logger.info("=" * 80)

    def reset(self):
        """重置所有指标"""
        with self._lock:
            self._metrics.clear()
            self._start_time = time.time()
            logger.info("性能监控已重置")


_performance_monitor = PerformanceMonitor()


def get_performance_monitor():
    """获取性能监控器单例"""
    return _performance_monitor

