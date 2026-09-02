# -*- coding: utf-8 -*-
"""FME 站点可用率与工单看板 API。

数据源与统计口径见 backend/services/site_availability_service.py 顶部说明。

GET /api/site-availability/filters
    -> 筛选器选项（supervisor / fme / 最近 12 个月）

GET /api/site-availability/overview
    ?month=YYYY-MM        统计月份（默认当前月）
    &supervisor=          Supervisor 过滤（空=全部）
    &fme=                 FME 过滤（空=全部）
    &tech=G|U|L|Tdd       时间维度列展开哪个制式（默认 L）
    &threshold=0.9965     未达标阈值（比率，默认 99.65%）
    &only_with_data=0|1   仅保留当前制式有数据的站点
    -> {meta, summary, sites}

GET /api/site-availability/tickets
    ?month=YYYY-MM&site_id=&site_name=
    -> 某站点整月 TT 明细
"""
import logging
import re
from datetime import date

from fastapi import APIRouter, Query

from backend.services import site_availability_service as svc

logger = logging.getLogger("site_availability")

router = APIRouter(prefix="/api/site-availability", tags=["site-availability"])

_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _current_month() -> str:
    d = date.today()
    return f"{d.year}-{d.month:02d}"


def _valid_month(m: str) -> str:
    if m and _MONTH_RE.match(m):
        return m
    return _current_month()


@router.get("/filters")
def filters():
    try:
        return svc.get_filters()
    except Exception as e:
        logger.exception("[site-availability/filters] 失败: %s", e)
        return {"supervisors": [], "fmes": [], "months": [_current_month()],
                "site_count": 0, "error": str(e)}


@router.get("/overview")
def overview(
    month: str = Query("", description="统计月份 YYYY-MM，默认当前月"),
    supervisor: str = Query("", description="Supervisor，空=全部"),
    fme: str = Query("", description="FME，空=全部"),
    tech: str = Query("L", description="时间维度展开的制式 G/U/L/Tdd"),
    threshold: float = Query(svc.DEFAULT_THRESHOLD, ge=0.0, le=1.0,
                             description="未达标阈值（比率，如 0.9965）"),
    only_with_data: int = Query(0, ge=0, le=1,
                                description="1=仅保留当前制式有数据的站点"),
):
    m = _valid_month(month)
    tk = tech if tech in svc.TECHS else "L"
    try:
        return svc.build_overview(
            month=m, supervisor=supervisor.strip(), fme=fme.strip(),
            tech=tk, threshold=threshold, only_with_data=bool(only_with_data),
        )
    except Exception as e:
        logger.exception("[site-availability/overview] 失败: %s", e)
        return {
            "meta": {"month": m, "days": [], "weeks": [], "tech": tk,
                     "threshold": threshold,
                     "generated_at": "", "elapsed_seconds": 0,
                     "warnings": [f"数据加载失败: {e}"], "sources": {}},
            "summary": {"site_count": 0, "by_tech": {},
                        "ticket_total": 0, "ticket_open": 0, "ticket_closed": 0},
            "sites": [],
        }


@router.get("/tickets")
def tickets(
    month: str = Query("", description="统计月份 YYYY-MM"),
    site_id: str = Query("", description="站点 ID"),
    site_name: str = Query("", description="站点名"),
):
    m = _valid_month(month)
    try:
        return svc.get_site_tickets(m, site_id=site_id.strip(), site_name=site_name.strip())
    except Exception as e:
        logger.exception("[site-availability/tickets] 失败: %s", e)
        return {"month": m, "site_id": site_id, "site_name": site_name,
                "total": 0, "open": 0, "rows": [], "error": str(e)}
