# -*- coding: utf-8 -*-
"""可用率多维矩阵（avail_ms）API。

数据源与口径见 `backend/services/avail_ms_service.py` 顶部说明 —— 它读的是
my_app 自持派生库 `data/avail_recon.sqlite3`（由任务 avail_recon_sync 每天重建），
不查主库、不发远端。

    GET /api/avail-ms/options
        -> {data_through, latest, days, weeks, months, threshold, warnings}

    GET /api/avail-ms/matrix
        ?period=day|week|month   周期粒度（默认 day）
        &value=YYYY-MM-DD|YYYY-Www|YYYY-MM   周期值，空=库里最新一期
        &threshold=0.9965        未达标阈值（比率）
        -> {meta, summary, groups[区域/制式/站点类型]}

    GET /api/avail-ms/trend
        ?period=&value=          窗口右端所在周期（空=库里最新一期）
        &points=30               窗口长度（期数），0=按档位默认（day 30 / week 12 / month 12）
        &threshold=0.9965
        -> {meta, categories[], dims{region[], tech[], site_type[]}} 每条线一个维度取值

    GET /api/avail-ms/drilldown
        ?level=period|tt         下钻类型
        &period=&value=          当前单元格所在周期
        &region=ALL|Montserrado|North East|South West|UNMATCHED
        &tech=2G|3G|4G           可空（空=全部制式）
        &site_type=Regular|Cooli|ERA|Other   可空（空=全部站点类型）
        -> level=period：{series 按日明细, breakdown 按调度组分解, history 近30期}
           level=tt    ：{rows TT 工单明细}
"""
import logging

from fastapi import APIRouter, Query

from backend.services import avail_ms_service as svc

logger = logging.getLogger("avail_ms")

router = APIRouter(prefix="/api/avail-ms", tags=["avail-ms"])


def _norm(period: str) -> str:
    return period if period in svc.PERIODS else "day"


def _norm_tech(tech: str) -> str:
    t = (tech or "").strip()
    return t if t in svc.TECHS else ""


def _norm_site_type(site_type: str) -> str:
    s = (site_type or "").strip()
    return s if s in svc.SITE_TYPES else ""


@router.get("/options")
def options():
    try:
        return svc.get_options()
    except Exception as e:  # noqa: BLE001
        logger.exception("[avail-ms/options] 失败: %s", e)
        return {"data_through": "", "latest": {}, "days": [], "weeks": [], "months": [],
                "threshold": svc.DEFAULT_THRESHOLD, "warnings": ["options_failed"],
                "error": str(e)}


@router.get("/matrix")
def matrix(
    period: str = Query("day", description="周期粒度 day|week|month"),
    value: str = Query("", description="周期值；空=库里最新一期"),
    threshold: float = Query(svc.DEFAULT_THRESHOLD, ge=0.0, le=1.0,
                             description="未达标阈值（比率，如 0.9965）"),
):
    p = _norm(period)
    try:
        return svc.build_matrix(period=p, value=(value or "").strip(), threshold=threshold)
    except Exception as e:  # noqa: BLE001 - 失败也要给前端一个可渲染的空矩阵
        logger.exception("[avail-ms/matrix] 失败 period=%s value=%s: %s", p, value, e)
        return {
            "meta": {"period": p, "value": value, "prev_value": "", "data_through": "",
                     "threshold": threshold, "generated_at": "", "elapsed_ms": 0,
                     "warnings": ["matrix_failed"], "unknown_cell_groups": [],
                     "error": str(e)},
            "summary": {"by_tech": {}, "unmatched_share": None, "regions": [],
                        "rows_in_period": 0},
            "groups": [],
        }


@router.get("/trend")
def trend(
    period: str = Query("day", description="周期粒度 day|week|month"),
    value: str = Query("", description="窗口右端所在周期值；空=库里最新一期"),
    points: int = Query(0, ge=0, le=svc.TREND_POINTS_MAX, description="窗口期数；0=按档位默认"),
    threshold: float = Query(svc.DEFAULT_THRESHOLD, ge=0.0, le=1.0),
):
    p = _norm(period)
    try:
        return svc.build_trends(period=p, value=(value or "").strip(),
                                points=points, threshold=threshold)
    except Exception as e:  # noqa: BLE001 - 失败给一个可渲染的空图
        logger.exception("[avail-ms/trend] 失败 period=%s value=%s: %s", p, value, e)
        return {"meta": {"period": p, "value": value, "start": "", "end": "", "points": 0,
                         "threshold": threshold, "generated_at": "",
                         "warnings": ["trend_failed"], "error": str(e)},
                "categories": [], "dims": {"region": [], "tech": [], "site_type": []}}


@router.get("/drilldown")
def drilldown(
    level: str = Query("period", description="period=时间明细|tt=工单明细"),
    period: str = Query("day", description="周期粒度 day|week|month"),
    value: str = Query("", description="周期值；空=库里最新一期"),
    region: str = Query(svc.REGION_ALL, description="ALL|区域名|UNMATCHED"),
    tech: str = Query("", description="2G|3G|4G，空=全部"),
    site_type: str = Query("", description="Regular|Cooli|ERA|Other，空=全部"),
    threshold: float = Query(svc.DEFAULT_THRESHOLD, ge=0.0, le=1.0),
):
    lv = "tt" if level == "tt" else "period"
    p = _norm(period)
    try:
        return svc.get_drilldown(
            level=lv, period=p, value=(value or "").strip(),
            region=(region or svc.REGION_ALL).strip(), tech=_norm_tech(tech),
            site_type=_norm_site_type(site_type), threshold=threshold,
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("[avail-ms/drilldown] 失败 level=%s period=%s value=%s: %s",
                         lv, p, value, e)
        return {"meta": {"level": lv, "period": p, "value": value, "region": region,
                         "tech": tech, "site_type": site_type, "threshold": threshold,
                         "generated_at": "", "warnings": ["drilldown_failed"],
                         "error": str(e)},
                "rows": [], "series": [], "breakdown": [], "history": [],
                "truncated": False, "cell": None}
