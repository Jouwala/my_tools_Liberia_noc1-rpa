# -*- coding: utf-8 -*-
"""MW UME 微波网络 Topology NOC Dashboard API

GET /api/mw-ume/topology?top_n=10            : 完整拓扑数据（Nodes/Edges/KPIs/TopRisks/Trends），自动取最新日期
GET /api/mw-ume/topology?date=2026-08-05     : 指定日期的拓扑数据（trends 仍为全部日期）
GET /api/mw-ume/topology?backbone=1          : 仅骨干网链路（两端 IP 均以 10. 开头），全部统计随子集重算
GET /api/mw-ume/topology?refresh=1           : 强制刷新（绕过 5 分钟缓存）
"""
import logging

from fastapi import APIRouter, Query

from backend.services.mw_ume.mw_ume_topology import get_topology

logger = logging.getLogger("mw_ume_router")
router = APIRouter(prefix="/api/mw-ume", tags=["mw-ume"])


@router.get("/topology")
def topology(top_n: int = Query(10, ge=1, le=50),
             refresh: int = Query(0),
             date: str = Query(None, description="所选日期 YYYY-MM-DD；缺省=最新可用日期"),
             backbone: int = Query(0, description="1=仅骨干网链路（两端 IP 均以 10. 开头）")):
    """返回微波网络拓扑（节点/链路/分级 KPI/Top 风险链路/历史趋势）。"""
    return get_topology(top_n=top_n, force=bool(refresh), date=date, backbone=bool(backbone))
