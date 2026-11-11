# -*- coding: utf-8 -*-
"""UME 拓扑图 API（四层共用，拓扑图数据一次返回，前端只画不算）。

端点
----
- `GET /api/ipran-topo/layers`                     页签清单（key / 中英名 / 是否有 UME 人工布局）
- `GET /api/ipran-topo/graph?layer=ipran&refresh=0` 完整图数据（网元 + 折叠后的边 + 元信息）

`layer` 走 `layers.LAYERS` 白名单，非法值直接 400，**不接受前端传任意 lid**。
不带 layer 时默认 `ipran`（IP RAN 光纤层），现有页面与旧调用方式行为不变。

`refresh=1` 绕过该层图缓存并重载站点坐标缓存（页面「刷新」按钮用），对应 UME
侧 8 次调用，约 1.5~3.0s；只清当前层，不会把另外三层缓存一起打掉。
取数口径、折叠规则、坐标来源与告警饱和度的说明见
`backend/services/ipran_topo/ipran_topo_service.py` 模块 docstring；层清单与
每层口径见同目录 `layers.py`。
"""
import logging

from fastapi import APIRouter, HTTPException, Query

from backend.services.ipran_topo import layers
from backend.services.ipran_topo import ipran_topo_service as svc
from backend.services.ipran_topo.layers import DEFAULT_LAYER

logger = logging.getLogger("ipran_topo_api")
router = APIRouter(prefix="/api/ipran-topo", tags=["ipran-topo"])


@router.get("/layers")
def list_layers():
    """前端页签清单。刻意不返回 lid，层映射只在后端白名单里。"""
    return {"layers": layers.public_list()}


@router.get("/graph")
def graph(
    layer: str = Query(DEFAULT_LAYER, description="拓扑层 key，见 /layers"),
    refresh: int = Query(0, ge=0, le=1, description="1 = 绕过缓存重新取数"),
):
    if layers.resolve_layer(layer) is None:
        raise HTTPException(status_code=400, detail=f"未知拓扑层: {layer}")
    try:
        if refresh:
            svc.clear_cache(layer)
            svc.refresh_site_index()
        return svc.build_graph(layer=layer, force=bool(refresh))
    except Exception as exc:
        logger.exception("[ipran-topo/graph] layer=%s failed: %s", layer, exc)
        return {
            "nodes": [],
            "edges": [],
            "meta": {
                "layer": layer,
                "ne": 0, "ext": 0, "rawLinks": 0, "foldedLinks": 0,
                "tierCounts": {}, "geo": {}, "geoMissSites": [], "geoFuzzyPairs": [],
                "critNe": 0, "cached": False,
                "warnings": [f"load_failed: {exc}"],
            },
        }
