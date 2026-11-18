# -*- coding: utf-8 -*-
"""CN 小时 KPI 看板 API（?page=cn_hourly_kpi）。

数据源与统计口径见 backend/services/cn_kpl/cn_hourly_kpi_service.py 顶部说明。

GET /api/cn-hourly-kpi/overview
    ?start=YYYY-MM-DD&end=YYYY-MM-DD   含端点的日期区间（默认最近 7 天，上限 31 天）
    ?force=1    跳过缓存，强制重新取数
    -> {meta:{db,start,end,count,failed,empty,elapsed_ms,cached}, widgets:[...]}

GET /api/cn-hourly-kpi/health
    -> {ok, db, elapsed_ms} | {ok:false, error}
"""
import logging

from fastapi import APIRouter, Query

from backend.services.cn_kpl import cn_hourly_kpi_service as svc

logger = logging.getLogger("cn_hourly_kpi")

router = APIRouter(prefix="/api/cn-hourly-kpi", tags=["cn-hourly-kpi"])


@router.get("/overview")
def overview(start: str = Query(None, description="起始日期 YYYY-MM-DD（含）"),
             end: str = Query(None, description="结束日期 YYYY-MM-DD（含）"),
             force: int = Query(0, description="1=跳过缓存强制刷新")):
    """整页数据：7 个组件（xGW 会话/吞吐容量 + MGW/MRFP 利用率）。"""
    return svc.get_overview(start=start, end=end, force=bool(force))


@router.get("/health")
def health():
    """远端只读 API 连通性探测。"""
    return svc.health()
