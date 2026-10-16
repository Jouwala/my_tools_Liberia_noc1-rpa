"""路线规划服务 —— OSRM 客户端 + 直线降级。

**用途**：GIS 人员图层里「点击某条 WO → 显示人员到该站点怎么走」。

**为什么自建 OSRM**（2026-10-16 决策）：项目此前**没有任何** routing/距离计算
代码；利比里亚属于内网交付环境，公共路由服务不保证可达与 SLA，故自建实例、
地址由配置给出。OSRM 二进制与地图数据是**运行依赖**（体积大），不入库 ——
与 nginx 的处理方式一致。

**配置读取**：优先级 `环境变量 OSRM_BASE_URL` → `backend/data/settings.json`
的 `osrm_base_url` → 空（未配置）。沿用 `config/remote_host.py` 的「每次调用
实时读，不固化为模块级常量」惯例，改配置无需重启进程。

**降级策略（重要，不得吞错返回空）**：OSRM 未配置 / 不可达 / 超时 / 无路网时，
返回 `mode="straight"` 的**直线连线 + haversine 距离**，并带 `degraded=True`
与原因。前端据此提示「路线引擎不可用，显示直线距离」。这样地图上**永远有一条线**，
而不是空白让人以为点了没反应。
"""
from __future__ import annotations

import json
import logging
import math
import os
import time
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

# backend/data/settings.json（与 config/remote_host.py 用同一个文件）
_SETTINGS_FILE = Path(__file__).resolve().parent.parent / "data" / "settings.json"

# OSRM 请求超时（秒）。路线是交互式点击触发，超过这个时间用户已经在等，
# 不如直接降级返回直线，体验更好。
_TIMEOUT = 6

# 进程内 TTL 缓存：同一对人（同一人反复点同一条 WO）短期内不重复打 OSRM。
# 缓存键含 profile；命中降级结果也缓存，避免 OSRM 挂着时每次都等 6 秒超时。
_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_TTL = 300  # 秒
_CACHE_MAX = 512  # 简单容量上限，防止无限增长


def get_osrm_base_url() -> str:
    """当前生效的 OSRM 基址（不含结尾斜杠）。未配置时返回空串。"""
    env = os.environ.get("OSRM_BASE_URL", "").strip()
    if env:
        return env.rstrip("/")
    try:
        if _SETTINGS_FILE.is_file():
            with open(_SETTINGS_FILE, "r", encoding="utf-8") as f:
                val = str(json.load(f).get("osrm_base_url", "") or "").strip()
                if val:
                    return val.rstrip("/")
    except Exception:
        # 配置读不到不应让整个功能挂掉 —— 走降级（直线）即可，但日志要留痕
        logger.warning("[SILENT-EXCEPT] 读取 osrm_base_url 失败，将走直线降级",
                       exc_info=True)
    return ""


def get_osrm_profile() -> str:
    """OSRM profile（OSRM 实例里构建的 profile 名，常见 driving / foot）。"""
    return (os.environ.get("OSRM_PROFILE", "").strip() or "driving")


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """两点大圆距离（米）。降级路径与「直线距离」显示都用它。"""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def _straight_result(lat1, lng1, lat2, lng2, reason: str) -> dict:
    """直线降级结果：geometry 是两点线段（GeoJSON LineString，坐标序 [lng, lat]）。"""
    return {
        "mode": "straight",
        "degraded": True,
        "reason": reason,
        "distance_m": round(haversine_m(lat1, lng1, lat2, lng2), 1),
        "duration_s": None,   # 直线无时长可言，明确为 null（前端显示「—」）
        "geometry": {
            "type": "LineString",
            # ⚠ GeoJSON 坐标是 [经度, 纬度] —— 与 OSRM 一致，也与 Leaflet 的
            #   [lat, lng] 相反。前端绘制时须交换回来。
            "coordinates": [[lng1, lat1], [lng2, lat2]],
        },
    }


def plan_route(lat1: float, lng1: float, lat2: float, lng2: float) -> dict:
    """规划 (lat1,lng1) → (lat2,lng2) 的路线。

    返回：
      - 成功：``{mode:"osrm", degraded:False, distance_m, duration_s, geometry}``
      - 降级：``{mode:"straight", degraded:True, reason, distance_m, duration_s:None, geometry}``

    **不抛异常** —— 任何失败都降级为直线，保证前端总有线可画。
    """
    base = get_osrm_base_url()
    if not base:
        return _straight_result(lat1, lng1, lat2, lng2, "osrm_not_configured")

    profile = get_osrm_profile()
    ck = (round(lat1, 5), round(lng1, 5), round(lat2, 5), round(lng2, 5), profile)
    hit = _CACHE.get(ck)
    now = time.time()
    if hit and (now - hit[0]) < _CACHE_TTL:
        return hit[1]

    # ⚠ OSRM 的参数顺序是 `{lng},{lat}`（**先经度后纬度**）—— 这是最常见的
    #   出错点，写反了会得到一条跑到地球另一边的路线或 no_route。
    url = (f"{base}/route/v1/{profile}/"
           f"{lng1},{lat1};{lng2},{lat2}"
           f"?overview=full&geometries=geojson")

    result = None
    try:
        resp = requests.get(url, timeout=_TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("code") == "Ok" and data.get("routes"):
                route = data["routes"][0]
                geom = route.get("geometry") or {}
                if geom.get("type") == "LineString" and geom.get("coordinates"):
                    result = {
                        "mode": "osrm",
                        "degraded": False,
                        "reason": None,
                        "distance_m": round(float(route.get("distance", 0.0)), 1),
                        "duration_s": round(float(route.get("duration", 0.0)), 1),
                        "geometry": {"type": "LineString",
                                     "coordinates": geom["coordinates"]},
                    }
                else:
                    result = _straight_result(lat1, lng1, lat2, lng2, "osrm_empty_geometry")
            else:
                # OSRM 明确回 no_route / NoSegment（该点不在路网附近）
                result = _straight_result(
                    lat1, lng1, lat2, lng2,
                    f"osrm_{str(data.get('code') or 'unknown').lower()}")
        else:
            result = _straight_result(lat1, lng1, lat2, lng2,
                                      f"osrm_http_{resp.status_code}")
    except requests.Timeout:
        result = _straight_result(lat1, lng1, lat2, lng2, "osrm_timeout")
    except Exception:
        logger.warning("[SILENT-EXCEPT] OSRM 请求失败，走直线降级", exc_info=True)
        result = _straight_result(lat1, lng1, lat2, lng2, "osrm_error")

    # 写缓存（含降级结果，避免 OSRM 挂掉时每次点都等超时）
    if len(_CACHE) >= _CACHE_MAX:
        # 简单清理：丢掉最旧的一批，不做 LRU 精细实现（够用即可）
        for k in sorted(_CACHE, key=lambda x: _CACHE[x][0])[: _CACHE_MAX // 4]:
            _CACHE.pop(k, None)
    _CACHE[ck] = (now, result)
    return result
