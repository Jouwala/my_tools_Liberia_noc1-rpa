# -*- coding: utf-8 -*-
"""FLM 可用率（avail_flm）API。

数据源与口径见 `backend/services/avail_flm_service.py` 顶部说明 —— 它读 my_app 自持派生库
`data/avail_recon.sqlite3`（任务 avail_recon_sync 每天重建），TT 读主库 `eflow_tt`，
复用 `avail_ms_service` 的聚合，不查远端。

    GET /api/avail-flm/options
        -> {data_through, latest, days, weeks, months, threshold, warnings}

    GET /api/avail-flm/matrix
        ?period=day|week|month   周期粒度（默认 day）
        &value=YYYY-MM-DD|YYYY-Www|YYYY-MM   周期值，空=库里最新一期
        &threshold=0.9965        未达标阈值（比率）
        -> {meta, summary{by_region,by_tech,all_regions}, groups[区域×制式, 区域×站点类型]}

    GET /api/avail-flm/trend
        ?period=&value=          窗口右端所在周期（空=库里最新一期）
        &points=0                窗口期数（0=按档位默认：日 30 / 周 12 / 月 12）
        &threshold=0.9965
        -> {meta, categories[], dims{region[], site_type[]}}   本页只画这两组线

    GET /api/avail-flm/tt
        ?period=&value=          周期（空=最新）
        &region=ALL|Montserrado|North East|South West   空=全部区域
        &site_type=Regular|Cooli|ERA                    空=全部站点类型
        -> {meta{total,returned,truncated,unassigned,start,end,warnings}, rows[]}
           页面级 TT 列表与下钻页签共用这个端点（口径见 service 顶部第 2 条）

    GET /api/avail-flm/drilldown
        ?level=period|tt &period= &value= &region= &tech= &site_type= &threshold=
        -> 与 /api/avail-ms/drilldown 同形（两页同一副明细口径）
"""
import logging

from fastapi import APIRouter, Query

from backend.services import avail_flm_service as svc
from backend.services import avail_ms_service as ms

logger = logging.getLogger("avail_flm")

router = APIRouter(prefix="/api/avail-flm", tags=["avail-flm"])


def _period(period: str) -> str:
    return period if period in ms.PERIODS else "day"


@router.get("/options")
def options():
    try:
        return svc.get_options()
    except Exception as e:  # noqa: BLE001
        logger.exception("[avail-flm/options] 失败: %s", e)
        return {"data_through": "", "latest": {}, "days": [], "weeks": [], "months": [],
                "threshold": ms.DEFAULT_THRESHOLD, "warnings": ["options_failed"],
                "error": str(e)}


@router.get("/matrix")
def matrix(
    period: str = Query("day", description="周期粒度 day|week|month"),
    value: str = Query("", description="周期值；空=库里最新一期"),
    threshold: float = Query(ms.DEFAULT_THRESHOLD, ge=0.0, le=1.0,
                             description="未达标阈值（比率，如 0.9965）"),
):
    p = _period(period)
    try:
        return svc.build_matrix(period=p, value=(value or "").strip(), threshold=threshold)
    except Exception as e:  # noqa: BLE001 - 失败也要给前端一个可渲染的空矩阵
        logger.exception("[avail-flm/matrix] 失败 period=%s value=%s: %s", p, value, e)
        return {
            "meta": {"period": p, "value": value, "prev_value": "", "data_through": "",
                     "threshold": threshold, "regions": list(svc.FLM_REGIONS),
                     "generated_at": "", "elapsed_ms": 0, "warnings": ["matrix_failed"],
                     "unknown_cell_groups": [], "error": str(e)},
            "summary": {"by_region": {}, "by_tech": {}, "all_regions": None,
                        "unmatched_share": None, "rows_in_period": 0},
            "groups": [],
        }


@router.get("/trend")
def trend(
    period: str = Query("day", description="周期粒度 day|week|month"),
    value: str = Query("", description="窗口右端所在周期值；空=库里最新一期"),
    points: int = Query(0, ge=0, le=ms.TREND_POINTS_MAX, description="窗口期数；0=按档位默认"),
    threshold: float = Query(ms.DEFAULT_THRESHOLD, ge=0.0, le=1.0),
):
    p = _period(period)
    try:
        return svc.build_trends(period=p, value=(value or "").strip(),
                                points=points, threshold=threshold)
    except Exception as e:  # noqa: BLE001 - 失败给一个可渲染的空图
        logger.exception("[avail-flm/trend] 失败 period=%s value=%s: %s", p, value, e)
        return {"meta": {"period": p, "value": value, "start": "", "end": "", "points": 0,
                         "threshold": threshold, "generated_at": "",
                         "warnings": ["trend_failed"], "error": str(e)},
                "categories": [], "dims": {"region": [], "site_type": []}}


@router.get("/tt")
def tt(
    period: str = Query("day", description="周期粒度 day|week|month"),
    value: str = Query("", description="周期值；空=库里最新一期"),
    region: str = Query("", description="空/ALL=全部区域，或 Montserrado|North East|South West"),
    site_type: str = Query("", description="Regular|Cooli|ERA，空=全部"),
):
    p = _period(period)
    try:
        return svc.get_tt(period=p, value=(value or "").strip(),
                          region=svc.normalize_region(region),
                          site_type=svc.normalize_site_type(site_type))
    except Exception as e:  # noqa: BLE001
        logger.exception("[avail-flm/tt] 失败 period=%s value=%s: %s", p, value, e)
        return {"meta": {"level": "tt", "period": p, "value": value, "region": region,
                         "site_type": site_type, "total": 0, "returned": 0,
                         "truncated": False, "start": "", "end": "",
                         "generated_at": "", "warnings": ["tt_read_failed"],
                         "error": str(e)},
                "rows": []}


@router.get("/drilldown")
def drilldown(
    level: str = Query("period", description="period=时间明细|tt=工单明细"),
    period: str = Query("day", description="周期粒度 day|week|month"),
    value: str = Query("", description="周期值；空=库里最新一期"),
    region: str = Query(ms.REGION_ALL, description="ALL|区域名|UNMATCHED"),
    tech: str = Query("", description="2G|3G|4G，空=全部"),
    site_type: str = Query("", description="Regular|Cooli|ERA，空=全部"),
    threshold: float = Query(ms.DEFAULT_THRESHOLD, ge=0.0, le=1.0),
):
    lv = "tt" if level == "tt" else "period"
    p = _period(period)
    reg = svc.normalize_region(region)
    try:
        return svc.get_drilldown(
            level=lv, period=p, value=(value or "").strip(), region=reg,
            tech=svc.normalize_tech(tech), site_type=svc.normalize_site_type(site_type),
            threshold=threshold,
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("[avail-flm/drilldown] 失败 level=%s period=%s value=%s: %s",
                         lv, p, value, e)
        return {"meta": {"level": lv, "period": p, "value": value, "region": reg,
                         "tech": tech, "site_type": site_type, "threshold": threshold,
                         "generated_at": "", "warnings": ["drilldown_failed"],
                         "error": str(e)},
                "rows": [], "series": [], "breakdown": [], "history": [],
                "truncated": False, "cell": None}
