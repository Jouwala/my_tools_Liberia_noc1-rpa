# -*- coding: utf-8 -*-
"""CXO Dashboard 缓存 API —— 只读透传 last-known-good 缓存给前端看板。

端点：
- GET /api/cxo-dashboard/cache   返回 data/cxo_dashboard/last_known_good.json 原文

缓存由 worker 定时任务 cxo_dashboard_cache_sync（backend/services/cxo_dashboard_cache.py）
每 10 分钟经本机 8790 VMAX 代理合并写入；前端 cxo_dashboard.html 打开时先应用缓存
再实时覆盖，VMAX/代理不可用时兜底显示最近可用数据。
"""
import json
import logging

from fastapi import APIRouter, Response

from backend.services.cxo_dashboard_cache import CACHE_FILE

logger = logging.getLogger(__name__)

router = APIRouter(tags=["cxo-dashboard"])


@router.get("/api/cxo-dashboard/cache")
def get_cxo_cache():
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            payload = f.read()
        json.loads(payload)  # 校验完整（写入走原子替换，读到的一定是整份）
    except FileNotFoundError:
        payload = json.dumps({"status": "ok", "keys": {}})
    except Exception as e:
        logger.warning("[cxo-dashboard] 缓存读取失败: %s", e)
        return Response(
            content=json.dumps({"status": "error", "error": str(e), "keys": {}}),
            status_code=500,
            media_type="application/json",
            headers={"Cache-Control": "no-store"},
        )
    return Response(
        content=payload,
        media_type="application/json",
        headers={"Cache-Control": "no-store"},
    )
