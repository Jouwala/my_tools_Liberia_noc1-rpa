# -*- coding: utf-8 -*-
"""SOC 多维趋势组合看板 API —— 只读，数据源 data/soc_trend/soc_trend.sqlite3。

与 /api/vmax-cxo-daily/*（小时明细门户代理路线）、/api/olib-soc/*（90 天经营看板）
完全独立：本路由只读本地归档库（由任务 47 soc_trend_sync 写入），数仓侧零访问，
接口本身不包含任何写操作。鉴权走全局会话中间件（main.py）。
"""
import logging
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from backend.services.soc_trend import soc_trend_service as svc
from backend.services.soc_trend import soc_trend_store as store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/soc-trend", tags=["soc-trend"])


def _conn():
    try:
        return store.connect(readonly=True)
    except Exception as exc:                                             # noqa: BLE001
        logger.warning("[soc-trend] 本地库打开失败: %s", exc)
        return None


def _no_store(payload, status: int = 200) -> JSONResponse:
    return JSONResponse(content=payload, status_code=status,
                        headers={"Cache-Control": "no-store"})


@router.get("/meta")
def meta():
    """可用日、类目就绪情况、成员字典、刷新时间（首屏第一请求）。"""
    conn = _conn()
    if conn is None:
        return _no_store({"error": "本地归档库不可用（等 soc_trend_sync 首次落盘）"}, 503)
    try:
        return _no_store(svc.meta_payload(conn))
    except Exception as exc:                                             # noqa: BLE001
        logger.exception("[soc-trend] meta 失败")
        return _no_store({"error": str(exc)}, 500)
    finally:
        conn.close()


@router.get("/series")
def series(gran: str = Query("hour", pattern="^(hour|day)$"),
           day: Optional[str] = Query(None, description="YYYY-MM-DD，默认取最新有数日"),
           cat: str = Query("flow"), dim: str = Query("total")):
    """趋势序列：hour=24 时 × D/D-1/D-7 三条线；day=最近 30 天。全指标一次带出。"""
    conn = _conn()
    if conn is None:
        return _no_store({"error": "本地归档库不可用"}, 503)
    try:
        meta = svc.meta_payload(conn)
        day_iso = day or (meta["latest_hour_day"] if gran == "hour" else meta["latest_day"])
        if not day_iso:
            return _no_store({"error": "暂无数据：等 soc_trend_sync 首次落盘"}, 503)
        payload = svc.series_payload(conn, gran, day_iso, cat, dim)
        payload["updated_at"] = meta["updated_at"]
        if payload.get("error"):
            return _no_store(payload, 400)
        return _no_store(payload)
    except Exception as exc:                                             # noqa: BLE001
        logger.exception("[soc-trend] series 失败")
        return _no_store({"error": str(exc)}, 500)
    finally:
        conn.close()


@router.get("/alarms")
def alarms(gran: str = Query("hour", pattern="^(hour|day)$"),
           day: Optional[str] = Query(None)):
    """重大告警分析（双基线越限 + 维度归因）与局部异常雷达，一次返回。"""
    conn = _conn()
    if conn is None:
        return _no_store({"error": "本地归档库不可用"}, 503)
    try:
        meta = svc.meta_payload(conn)
        day_iso = day or (meta["latest_hour_day"] if gran == "hour" else meta["latest_day"])
        if not day_iso:
            return _no_store({"error": "暂无数据"}, 503)
        payload = svc.alarms_payload(conn, gran, day_iso)
        payload["updated_at"] = meta["updated_at"]
        return _no_store(payload)
    except Exception as exc:                                             # noqa: BLE001
        logger.exception("[soc-trend] alarms 失败")
        return _no_store({"error": str(exc)}, 500)
    finally:
        conn.close()


@router.get("/dict")
def dict_entries():
    """指标字典：口径、来源计数器、适用类目、告警规则。"""
    return _no_store(svc.dict_payload())
