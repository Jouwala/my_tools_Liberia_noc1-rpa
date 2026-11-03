# -*- coding: utf-8 -*-
"""县（Province/County）维度可用率看板 API。

数据源与统计口径见 `backend/services/avail_county_service.py` 顶部说明。

    GET /api/avail-county/options
        -> {months, current_month, counties[], techs, threshold, data_through, warnings}

    GET /api/avail-county/matrix
        ?period=day|week        周期粒度（默认 day）
        &month=YYYY-MM          统计月份（默认当前月）
        &value=YYYY-MM-DD|YYYY-Www   周期值，空=该月最后一期
        &threshold=0.9965       未达标阈值（比率）
        -> {meta, summary, rows[]}  行=县，列=2G/3G/4G

    GET /api/avail-county/trend
        ?period=&month=&value=  曲线窗口（本月内）
        &county=                县名，空=全网
        &threshold=
        -> {meta, categories[], series[]}  每条线一个制式

    GET /api/avail-county/drilldown
        ?level=county_sites|site_daily|tt
        &period=&month=&value=&county=&tech=&threshold=
        -> level=county_sites：某县某制式的站点级明细
           level=site_daily  ：某站点的逐日明细
           level=tt          ：某县的 TT 工单明细
"""
import logging
import re

from fastapi import APIRouter, Query

from backend.services import avail_county_service as svc

logger = logging.getLogger("avail_county")

router = APIRouter(prefix="/api/avail-county", tags=["avail-county"])

_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _current_month() -> str:
    from datetime import date
    d = date.today()
    return f"{d.year}-{d.month:02d}"


def _valid_month(m: str) -> str:
    return m if (m and _MONTH_RE.match(m)) else _current_month()


@router.get("/options")
def options():
    try:
        return svc.get_options()
    except Exception as e:
        logger.exception("[avail-county/options] 失败: %s", e)
        return {
            "months": [_current_month()], "current_month": _current_month(),
            "counties": [], "techs": list(svc.TECHS),
            "threshold": svc.DEFAULT_THRESHOLD, "data_through": "",
            "warnings": ["options_failed"], "error": str(e),
        }


@router.get("/matrix")
def matrix(
    month: str = Query("", description="统计月份 YYYY-MM，默认当前月"),
    period: str = Query("day", description="周期粒度 day|week"),
    value: str = Query("", description="周期值 YYYY-MM-DD / YYYY-Www，空=该月最后一期"),
    threshold: float = Query(svc.DEFAULT_THRESHOLD, ge=0.0, le=1.0,
                             description="未达标阈值（比率，如 0.9965）"),
):
    m = _valid_month(month)
    try:
        return svc.build_matrix(month=m, period=period, value=value.strip(),
                                threshold=threshold)
    except Exception as e:
        logger.exception("[avail-county/matrix] 失败: %s", e)
        return {
            "meta": {"month": m, "period": period, "value": "", "days": [],
                     "counties": [], "techs": list(svc.TECHS),
                     "threshold": threshold, "data_through": "",
                     "covered_days": [], "generated_at": "",
                     "elapsed_ms": 0, "warnings": ["matrix_failed"]},
            "summary": {"by_tech": {}, "county_count": 0},
            "rows": [], "error": str(e),
        }


@router.get("/trend")
def trend(
    month: str = Query("", description="统计月份 YYYY-MM"),
    period: str = Query("day", description="周期粒度 day|week"),
    value: str = Query("", description="窗口右端所在周期（空=该月最后一期）"),
    county: str = Query("", description="县名，空=全网"),
    threshold: float = Query(svc.DEFAULT_THRESHOLD, ge=0.0, le=1.0),
):
    m = _valid_month(month)
    try:
        return svc.build_trend(month=m, period=period, value=value.strip(),
                               county=county.strip(), threshold=threshold)
    except Exception as e:
        logger.exception("[avail-county/trend] 失败: %s", e)
        return {
            "meta": {"month": m, "period": period, "county": county,
                     "threshold": threshold, "points": 0, "data_through": "",
                     "generated_at": "", "warnings": ["trend_failed"]},
            "categories": [], "series": [], "error": str(e),
        }


@router.get("/drilldown")
def drilldown(
    level: str = Query("county_sites",
                       description="下钻类型 county_sites|site_daily|tt"),
    month: str = Query("", description="统计月份 YYYY-MM"),
    period: str = Query("day", description="周期粒度 day|week"),
    value: str = Query("", description="周期值，空=该月最后一期"),
    county: str = Query("", description="县名；level=site_daily 时传 site_key"),
    tech: str = Query("", description="制式 2G|3G|4G，空=不限"),
    threshold: float = Query(svc.DEFAULT_THRESHOLD, ge=0.0, le=1.0),
):
    m = _valid_month(month)
    try:
        return svc.get_drilldown(level=level.strip(), month=m, period=period,
                                 value=value.strip(), county=county.strip(),
                                 tech=tech.strip(), threshold=threshold)
    except Exception as e:
        logger.exception("[avail-county/drilldown] 失败: %s", e)
        return {
            "meta": {"level": level, "period": period, "value": "",
                     "total": 0, "returned": 0, "truncated": False,
                     "warnings": ["drilldown_failed"]},
            "rows": [], "error": str(e),
        }
