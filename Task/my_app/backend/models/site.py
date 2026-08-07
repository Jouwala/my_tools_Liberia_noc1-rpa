"""站点/拓扑数据表反射模型（app.db）

master_site_db / topology 由 import_topology.py 从 Excel 导入，
列集合随源文件模板变化，采用与 eflow.py 相同的 automap 反射策略。

用法：
    from backend.models.site import get_site_classes
    classes = get_site_classes()
    site_cls = classes.get("master_site_db")
"""
import logging

from sqlalchemy.ext.automap import automap_base

from backend.database import engine

logger = logging.getLogger(__name__)

_SITE_TABLES = ("master_site_db", "site_db", "topology")
_cache = None


def get_site_classes(refresh: bool = False) -> dict:
    """返回 {表名: automap 类}，仅包含站点/拓扑相关表"""
    global _cache
    if _cache is None or refresh:
        try:
            base = automap_base()
            base.prepare(autoload_with=engine, reflect=True)
            mapping = {name: base.classes[name] for name in base.classes.keys()}
            _cache = {name: mapping[name] for name in _SITE_TABLES if name in mapping}
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[site-models] 反射失败，降级为空映射: {e}")
            _cache = {}
    return _cache
