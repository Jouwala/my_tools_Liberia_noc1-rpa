"""
统一日志系统模块
为所有子应用提供统一的日志记录功能
"""

import logging
import os
from datetime import datetime
from pathlib import Path


class UnifiedLogger:
    """统一日志管理器"""

    _loggers = {}

    @classmethod
    def get_logger(cls, name, log_dir='logs', level=logging.DEBUG):
        """
        获取或创建日志记录器

        Args:
            name: 日志记录器名称
            log_dir: 日志目录
            level: 日志级别

        Returns:
            logging.Logger: 日志记录器实例
        """
        if name in cls._loggers:
            return cls._loggers[name]

        logger = logging.getLogger(name)
        logger.setLevel(level)

        # 清除已有的 handlers，确保使用新的配置
        logger.handlers.clear()

        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(
            log_path / f'{name}.log',
            encoding='utf-8'
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        cls._loggers[name] = logger
        return logger

    @classmethod
    def clear_handlers(cls, name):
        """清除指定日志记录器的所有处理器"""
        if name in cls._loggers:
            logger = cls._loggers[name]
            logger.handlers.clear()


def get_logger(name='app'):
    """快捷方法：获取日志记录器"""
    return UnifiedLogger.get_logger(name)
