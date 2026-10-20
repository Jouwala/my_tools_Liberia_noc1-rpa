"""FME 级 WO 与站点可用率排名 API。"""
import logging
import re
from datetime import date

from fastapi import APIRouter, Query

from backend.services.fme_data import fme_ranking_service as svc

logger = logging.getLogger("fme_ranking")
router = APIRouter(prefix="/api/fme-ranking", tags=["fme-ranking"])
_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _current_month() -> str:
    today = date.today()
    return f"{today.year:04d}-{today.month:02d}"


@router.get("/filters")
def filters():
    try:
        return svc.get_filters()
    except Exception as exc:
        logger.exception("[fme-ranking/filters] failed: %s", exc)
        return {"supervisors": [], "fmes": [], "months": [_current_month()], "site_count": 0, "techs": list(svc.TECHS), "error": str(exc)}


@router.get("/overview")
def overview(
    month: str = Query("", description="统计月份 YYYY-MM"),
    tech: str = Query(svc.DEFAULT_TECH, description="G/U/L/Tdd"),
    supervisor: str = Query("", max_length=120),
    fme: str = Query("", max_length=120),
    threshold: float = Query(svc.DEFAULT_THRESHOLD, ge=0.0, le=1.0),
):
    month = month if _MONTH_RE.match(month or "") else _current_month()
    tech = tech if tech in svc.TECHS else svc.DEFAULT_TECH
    try:
        return svc.build_overview(month, tech=tech, supervisor=supervisor, fme=fme, threshold=threshold)
    except Exception as exc:
        logger.exception("[fme-ranking/overview] failed: %s", exc)
        return {"meta": {"month": month, "tech": tech, "threshold": threshold, "warnings": [f"load_failed: {exc}"]},
                "filters": {"month": month, "tech": tech, "supervisor": supervisor, "fme": fme},
                "summary": {"fme_count": 0, "site_count": 0, "sites_with_availability": 0, "wo_total": 0, "wo_open": 0, "wo_closed": 0},
                "rows": []}


@router.get("/wo-drilldown")
def wo_drilldown(
    month: str = Query("", description="统计月份 YYYY-MM"),
    fme: str = Query("", max_length=120, description="FME 名称；为空表示全部"),
    supervisor: str = Query("", max_length=120),
    limit: int = Query(800, ge=1, le=5000),
):
    """某 FME 名下的 WO 明细（下钻）。"""
    month = month if _MONTH_RE.match(month or "") else _current_month()
    try:
        return svc.build_wo_drilldown(month, fme=fme, supervisor=supervisor, limit=limit)
    except Exception as exc:
        logger.exception("[fme-ranking/wo-drilldown] failed: %s", exc)
        return {"month": month, "fme": fme, "total": 0, "open": 0, "rows": [], "columns": [], "error": str(exc)}


@router.get("/site-drilldown")
def site_drilldown(
    month: str = Query("", description="统计月份 YYYY-MM"),
    fme: str = Query("", max_length=120, description="FME 名称；为空表示全部"),
    supervisor: str = Query("", max_length=120),
    tech: str = Query(svc.DEFAULT_TECH, description="G/U/L/Tdd"),
    threshold: float = Query(svc.DEFAULT_THRESHOLD, ge=0.0, le=1.0),
    limit: int = Query(800, ge=1, le=5000),
):
    """某 FME 名下的站点级可用率与 WO 明细（下钻）。"""
    month = month if _MONTH_RE.match(month or "") else _current_month()
    tech = tech if tech in svc.TECHS else svc.DEFAULT_TECH
    try:
        return svc.build_site_drilldown(month, fme=fme, supervisor=supervisor, tech=tech,
                                        threshold=threshold, limit=limit)
    except Exception as exc:
        logger.exception("[fme-ranking/site-drilldown] failed: %s", exc)
        return {"month": month, "fme": fme, "tech": tech, "total": 0, "rows": [], "columns": [], "error": str(exc)}
