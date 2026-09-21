# -*- coding: utf-8 -*-
"""CN KPI 看板 API（原 my-finebi「CN KPI」看板原生重建）。

数据源与统计口径见 backend/services/cn_kpi_service.py 顶部说明。

GET /api/cn-kpi/overview
    ?start=YYYY-MM-DD     自定义起始日期（含）；留空 = 近 31 天
    &end=YYYY-MM-DD       自定义结束日期（不含）；留空 = 今天+1天
    &force=1              跳过 60s 缓存，强制重新取数
    -> {meta:{db,host,count,failed,elapsed_ms,cached,start,end},
        title, title_html,
        widgets:[{id,title,chart,pivot,pct,sql,columns,rows,error}]}

GET /api/cn-kpi/health
    -> {ok, host, db, elapsed_ms} | {ok:false, error}

说明：widgets[].sql 会回传**实际执行**的 SQL（占位符已替换），
供前端导出 Excel 时把口径一并写进表头，便于复核。
"""
import logging

from fastapi import APIRouter, HTTPException, Query

from backend.services import cn_kpi_service as svc

logger = logging.getLogger("cn_kpi")

router = APIRouter(prefix="/api/cn-kpi", tags=["cn-kpi"])


@router.get("/overview")
def overview(
    start: str = Query("", description="起始日期 YYYY-MM-DD（含），留空=近31天"),
    end: str = Query("", description="结束日期 YYYY-MM-DD（不含），留空=今天"),
    force: int = Query(0, description="1=跳过缓存强制刷新"),
):
    """整页数据：18 个组件并发取数（TTL 60s 缓存，按区间分行）。"""
    try:
        return svc.get_overview(force=bool(force), start=start or None, end=end or None)
    except ValueError as e:
        # 日期格式非法 / 起止倒置 —— 属客户端错误
        raise HTTPException(400, str(e)) from e


@router.get("/health")
def health():
    """远端只读 API 连通性探测。"""
    return svc.health()
