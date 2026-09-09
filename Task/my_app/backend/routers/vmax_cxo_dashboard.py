# -*- coding: utf-8 -*-
"""VMAX CXO 原版视觉看板专用 API。

与现有 /api/cxo-dashboard/cache 分离：旧接口继续服务简化版看板；本路由把
last-known-good 缓存裁剪成原版 Summary 大屏需要的稳定数据模型。
"""
import json
import logging
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/vmax-cxo-dashboard", tags=["vmax-cxo-dashboard"])
_ROOT = Path(__file__).resolve().parents[2]
CACHE_FILE = _ROOT / "data" / "cxo_dashboard" / "last_known_good.json"
SERVICE_MANIFEST = {
    "Mobility": [391, 392, 393], "Voice": [412, 413, 414],
    "Data": [431, 433, 434], "Video": [451],
    "SMS": [202, 204, 205, 206, 207, 208],
    "Web Browse": [221, 223, 224, 225, 226, 227, 228],
    "Game": [242, 243, 244, 245], "OTTVoice": list(range(262, 273)),
    "OTTVideo": [282, 283],
}
NET_TABS = {
    1: [391, 392, 393], 2: [411, 412, 413, 414],
    3: [431, 433, 434], 4: [451], 5: [471, 472, 473],
}


def _data(keys: Dict[str, Any], name: str) -> Dict[str, Any]:
    entry = keys.get(name)
    if not isinstance(entry, dict):
        return {}
    value = entry.get("data")
    return value if isinstance(value, dict) else {}


def _read_cache() -> Dict[str, Any]:
    with open(CACHE_FILE, "r", encoding="utf-8") as stream:
        payload = json.load(stream)
    return payload if isinstance(payload, dict) else {}


def _overview_view(raw: Dict[str, Any]) -> Dict[str, Any]:
    """只返回 KPI 展示字段，禁止把 queryData/cookie 等内部响应透出。"""
    return {key: raw.get(key) for key in ("showName", "kpiValue", "unit")}


def _trend_view(raw: Dict[str, Any]) -> Dict[str, Any]:
    """趋势只需 ECharts option；剔除 mars/queryParam 等大字段和会话信息。"""
    return {
        "showName": raw.get("showName"),
        "xData": raw.get("xData") or [],
        "yData": raw.get("yData") or [],
        "option": raw.get("option") if isinstance(raw.get("option"), dict) else {},
    }


def _chart_view(raw: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "title": raw.get("title"),
        "option": raw.get("option") if isinstance(raw.get("option"), dict) else {},
    }


def _map_view(raw: Dict[str, Any]) -> Dict[str, Any]:
    return {key: raw.get(key) for key in ("title", "tooltip", "visualMap", "series")}


@router.get("/summary")
def get_vmax_cxo_summary():
    """返回原版 Summary 大屏所需 KPI、趋势、用户与地域数据。"""
    try:
        cache = _read_cache()
        keys = cache.get("keys") if isinstance(cache.get("keys"), dict) else {}
        overview = {
            str(info_id): _overview_view(_data(keys, f"summary/overview_{info_id}"))
            for info_id in (131, 132, 133, 134)
        }
        trends = {
            str(graph_id): _trend_view(_data(keys, f"summary/trend_{graph_id}"))
            for graph_id in (91, 92, 93, 94, 95, 99)
        }
        body = {
            "status": "ok",
            "source": "cache",
            "updated_at": cache.get("updated_at"),
            "summary": {
                "overview": overview,
                "trends": trends,
                "geMap": _map_view(_data(keys, "summary/geMap")),
                "userData": _chart_view(_data(keys, "summary/userData")),
                "cityUser": _chart_view(_data(keys, "summary/cityUser")),
            },
        }
        return JSONResponse(body, headers={"Cache-Control": "no-store"})
    except FileNotFoundError:
        return JSONResponse(
            {"status": "ok", "source": "empty", "updated_at": None, "summary": {}},
            headers={"Cache-Control": "no-store"},
        )
    except Exception as exc:
        logger.exception("[vmax-cxo-dashboard] failed to read dashboard cache")
        return JSONResponse(
            {"status": "error", "source": "error", "summary": {}},
            status_code=500,
            headers={"Cache-Control": "no-store"},
        )


def _indicator_view(raw: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "title": raw.get("title") or raw.get("name"),
        "name": raw.get("name"),
        "value": raw.get("value"),
        "option": raw.get("option") if isinstance(raw.get("option"), dict) else {},
    }


@router.get("/service/{business}")
def get_vmax_cxo_service(business: str):
    """返回指定 Service 业务的地图、指标、原因分析和 TopN。"""
    if business not in SERVICE_MANIFEST:
        return JSONResponse({"status": "error", "error": "unknown business"}, status_code=404)
    try:
        cache = _read_cache()
        keys = cache.get("keys") if isinstance(cache.get("keys"), dict) else {}
        indicators = [
            {"id": str(info_id), **_indicator_view(_data(keys, f"service/{business}/indicator/{info_id}"))}
            for info_id in SERVICE_MANIFEST[business]
        ]
        delimit = _data(keys, f"service/{business}/delimit")
        limit = _data(keys, f"service/{business}/limit")
        return JSONResponse({
            "status": "ok", "source": "cache", "updated_at": cache.get("updated_at"),
            "business": business, "indicators": indicators,
            "map": _chart_view(_data(keys, f"service/{business}/map")),
            "delimit": _chart_view(delimit),
            "limit": {"header": limit.get("header") or [], "data": limit.get("data") or []},
        }, headers={"Cache-Control": "no-store"})
    except Exception as exc:
        logger.exception("[vmax-cxo-dashboard] service failed")
        return JSONResponse({"status": "error", "source": "error"}, status_code=500)


@router.get("/network/{tab_id}")
def get_vmax_cxo_network(tab_id: int):
    """返回指定 Network 页签的指标数据。"""
    if tab_id not in NET_TABS:
        return JSONResponse({"status": "error", "error": "unknown network tab"}, status_code=404)
    try:
        cache = _read_cache()
        keys = cache.get("keys") if isinstance(cache.get("keys"), dict) else {}
        indicators = [
            {"id": str(info_id), **_indicator_view(_data(keys, f"net/tab/{tab_id}/indicator/{info_id}"))}
            for info_id in NET_TABS[tab_id]
        ]
        return JSONResponse({
            "status": "ok", "source": "cache", "updated_at": cache.get("updated_at"),
            "tab": tab_id, "indicators": indicators,
            "map": _chart_view(_data(keys, f"net/tab/{tab_id}/map") or _data(keys, "net/map")),
        }, headers={"Cache-Control": "no-store"})
    except Exception as exc:
        logger.exception("[vmax-cxo-dashboard] network failed")
        return JSONResponse({"status": "error", "source": "error"}, status_code=500)


@router.get("/status")
def get_vmax_cxo_status():
    """轻量健康检查，供部署检查和大屏状态监控。"""
    try:
        cache = _read_cache()
        keys = cache.get("keys") if isinstance(cache.get("keys"), dict) else {}
        return {
            "status": "ok",
            "cache_exists": True,
            "updated_at": cache.get("updated_at"),
            "cached_components": len(keys),
        }
    except FileNotFoundError:
        return {"status": "ok", "cache_exists": False, "updated_at": None, "cached_components": 0}
    except Exception as exc:
        logger.warning("[vmax-cxo-dashboard] status failed: %s", exc)
        return JSONResponse({"status": "error", "source": "error"}, status_code=500)
