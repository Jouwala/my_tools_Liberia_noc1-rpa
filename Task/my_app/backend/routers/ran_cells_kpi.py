# -*- coding: utf-8 -*-
"""RAN 2G/3G/4G Cells KPI 看板 API。

数据源与统计口径见 backend/services/ran_cells_kpi_service.py 顶部说明。

GET /api/ran-cells-kpi/overview
    ?month=YYYY-MM        统计月份（默认当前月）
    &threshold=0.9965     达标值（比率，默认 99.65%）
    &prefer_db=1          1=优先读物化库（任务写入），0=强制实时聚合原始库
    -> {meta, techs:[{tech,label,desc,roster_cells,days,month}]}

GET /api/ran-cells-kpi/cells（看板数字下钻）
    ?month=YYYY-MM        统计月份（默认当前月）
    &tech=2G|3G|4G        制式（必填）
    &day=YYYY-MM-DD       日期；留空表示整月汇总（逐小区月均可用率）
    &threshold=0.9965     达标值（比率，默认 99.65%）
    &scope=all            过滤范围 all/meeting/below/blank，与看板指标行对应
    -> {tech,label,desc,month,day,threshold,scope,roster_cells,
        total,meeting,below,blank,
        rows:[{cell,ratio,days_with_data,status,
               cell_id,site_id,site_name,ne,subnet,band,
               days_meeting,days_below}]}   # 后 3 个仅整月下钻
"""
import logging
import re
from datetime import date

from fastapi import APIRouter, Query

from backend.services import ran_cells_kpi_service as svc

logger = logging.getLogger("ran_cells_kpi")

router = APIRouter(prefix="/api/ran-cells-kpi", tags=["ran-cells-kpi"])

_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_DAY_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")


def _current_month() -> str:
    d = date.today()
    return f"{d.year}-{d.month:02d}"


def _valid_month(m: str) -> str:
    return m if (m and _MONTH_RE.match(m)) else _current_month()


@router.get("/overview")
def overview(
    month: str = Query("", description="统计月份 YYYY-MM，默认当前月"),
    threshold: float = Query(svc.DEFAULT_THRESHOLD, gt=0.0, le=1.0,
                             description="达标值（比率，默认 0.9965 = 99.65%）"),
    prefer_db: int = Query(1, ge=0, le=1,
                           description="1=优先读物化库；0=强制实时聚合原始库"),
):
    m = _valid_month(month)
    try:
        return svc.load_overview(m, threshold, prefer_db=bool(prefer_db))
    except Exception as e:
        logger.exception("[ran-cells-kpi/overview] 失败: %s", e)
        return {
            "meta": {"month": m, "threshold": threshold, "days": [],
                     "source": "", "generated_at": "", "elapsed_seconds": 0,
                     "warnings": [f"load_failed: {e}"]},
            "techs": [],
        }


@router.get("/cells")
def cells(
    month: str = Query("", description="统计月份 YYYY-MM，默认当前月"),
    tech: str = Query("", description="制式：2G / 3G / 4G"),
    day: str = Query("", description="日期 YYYY-MM-DD；留空表示整月汇总"),
    threshold: float = Query(svc.DEFAULT_THRESHOLD, gt=0.0, le=1.0,
                             description="达标值（比率，默认 0.9965 = 99.65%）"),
    scope: str = Query("all", description="过滤范围：all / meeting / below / blank"),
):
    """小区级明细（看板数字下钻）。

    rows 每行除 cell / ratio / days_with_data / status 外，还带身份信息：
    cell_id（小区 ID）、site_id / site_name（站点 ID 与名称）、
    ne（网元：BSC / RNC / eNodeB）、subnet（子网）、band（频段，4G FDD 无此列）；
    整月下钻（day 留空）另有 days_meeting / days_below。

    版本标记（用于确认线上 7038 是否已加载本版本代码，见 /openapi.json）：RCK_META_V2
    """
    m = _valid_month(month)
    d = day if (day and _DAY_RE.match(day)) else ""
    if tech not in svc.TECH_SPEC:
        return {
            "tech": tech, "label": "", "desc": "", "month": m, "day": d,
            "threshold": threshold, "scope": scope, "roster_cells": 0,
            "total": 0, "meeting": 0, "below": 0, "blank": 0, "rows": [],
            "warnings": [f"invalid_tech: {tech}"],
        }
    try:
        return svc.compute_tech_cells(tech, m, d, threshold, scope)
    except Exception as e:
        logger.exception("[ran-cells-kpi/cells] 失败: %s", e)
        return {
            "tech": tech, "label": svc.TECH_SPEC[tech]["label"],
            "desc": svc.TECH_SPEC[tech]["desc"], "month": m, "day": d,
            "threshold": threshold, "scope": scope, "roster_cells": 0,
            "total": 0, "meeting": 0, "below": 0, "blank": 0, "rows": [],
            "warnings": [f"load_failed: {e}"],
        }
