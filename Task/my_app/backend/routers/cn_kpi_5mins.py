# -*- coding: utf-8 -*-
"""CN KPI 5 分钟看板 API（?page=cn_kpi_5mins）。

数据源与统计口径见 backend/services/cn_kpi_5mins_service.py 顶部说明。

GET /api/cn-kpi-5mins/overview
    ?force=1    跳过 30s 缓存，强制重新取数
    -> {meta:{db,count,failed,empty,elapsed_ms,cached},
        title,
        widgets:[{id,title,chart,pivot,pct,sql,columns,rows,error,empty,empty_reason}]}

GET /api/cn-kpi-5mins/health
    -> {ok, db, elapsed_ms} | {ok:false, error}

说明：窗口固定为「今天 + 昨天 + 7 天前」（Day0/Day1/Day7 叠画），因此本端点**不接收**时间区间
参数 —— 三个日子由 SQL 里的 date('now') / date('now','-1 day') / date('now','-7 day') 决定，
随系统日期自然滚动。
"""
import logging

from fastapi import APIRouter, Query

from backend.services import cn_kpi_5mins_service as svc

logger = logging.getLogger("cn_kpi_5mins")

router = APIRouter(prefix="/api/cn-kpi-5mins", tags=["cn-kpi-5mins"])


@router.get("/overview")
def overview(force: int = Query(0, description="1=跳过缓存强制刷新")):
    """整页数据：8 个有数据组件 + 3 个空态组件（上游无 5 分钟粒度）。"""
    return svc.get_overview(force=bool(force))


@router.get("/health")
def health():
    """远端只读 API 连通性探测。"""
    return svc.health()
