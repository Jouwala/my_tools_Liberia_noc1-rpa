"""eFlow 动态数据表反射模型（app.db）

eflow_tt / eflow_wo / eflow_cr / eflow_pm / eflow_site / eflow_person、
realtime_alarm / history_alarm 等表由 sync_from_eflow_api.py 按 API 返回
字段**动态建表 + ALTER ADD COLUMN**，列集合会随网管版本演进，
因此不做静态 ORM 建模，改用 automap 反射按需加载。

用法：
    from backend.models.eflow import get_eflow_classes
    classes = get_eflow_classes()          # 反射全部 eflow/alarm 表
    tt = classes.get("eflow_tt")           # 表不存在时返回 None
    rows = session.query(tt).limit(10).all()

注意：反射结果按进程缓存；同步任务新增列后需重启或调用 refresh_eflow_classes()。
"""
import logging

from sqlalchemy.ext.automap import automap_base
from sqlalchemy.orm import Session

from backend.database import engine

logger = logging.getLogger(__name__)

_automap_cache = None


def _reflect():
    """反射主库中全部表并生成 automap 类（含 eflow_* / *_alarm / _metadata 等动态表）"""
    base = automap_base()
    try:
        base.prepare(autoload_with=engine, reflect=True)
    except Exception as e:  # noqa: BLE001 - 库文件缺失/被锁时降级为空
        logger.warning(f"[eflow-models] 反射失败，降级为空映射: {e}")
        return {}
    return {name: base.classes[name] for name in base.classes.keys()}


def get_eflow_classes(refresh: bool = False) -> dict:
    """返回 {表名: automap 类}，缺失表不在字典中（调用方 .get() 判空）"""
    global _automap_cache
    if _automap_cache is None or refresh:
        _automap_cache = _reflect()
    return _automap_cache


def refresh_eflow_classes() -> dict:
    """同步任务新增列后强制重新反射"""
    return get_eflow_classes(refresh=True)


def open_session() -> Session:
    """配套会话（使用方负责 close 或用 with 语义包装）"""
    from backend.database import SessionLocal
    return SessionLocal()
