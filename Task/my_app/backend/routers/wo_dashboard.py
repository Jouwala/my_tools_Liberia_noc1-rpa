"""WO 看板 API（`page=wo`）。

与 TT 看板（`/api/tt-wo-dashboard/*`）**版式一致、数据源不同**：
TT 页读 `eflow_tt`，本页读 `eflow_wo`。两条端点各自独立，互不影响 ——
TT&WO 看板（`page=ttwo`）与 TT 看板是线上在看的页面，不能被 WO 的改动波及。

计算逻辑全部在 `backend/services/wo_dashboard_service.py`，本文件只做参数绑定。
"""
from fastapi import APIRouter, Query

from backend.services.wo_dashboard_service import wo_drilldown, wo_overview

router = APIRouter(prefix="/api/wo-dashboard", tags=["wo-dashboard"])


@router.get("/overview")
def wo_dashboard_overview(
    time_start: str = Query(None),
    time_end: str = Query(None),
    region: str = Query(None),
    adv: str = Query(None, description="高级过滤，JSON 对象 {站点列名: 精确值}"),
):
    """WO 看板综合数据：统计（严重度 / SLA 状态 / 状态）+ MTTR 趋势（按级别 × 日周月）。

    过滤口径与 `page=tt` 对齐（同一 `alarm_occur_time`、同一站点 JOIN、同一高级过滤）。
    **无 owner（ZTE/3rd）过滤**：该归属的定义是「TT 的 wo_no 是否非空」，
    在 WO 表上每行本身就是一个 WO，没有对应概念。
    """
    return wo_overview(time_start=time_start, time_end=time_end, region=region, adv=adv)


@router.get("/drilldown")
def wo_dashboard_drilldown(
    dimension: str = Query("all_wo"),
    value: str = Query(None),
    time_start: str = Query(None),
    time_end: str = Query(None),
    region: str = Query(None),
    adv: str = Query(None, description="高级过滤，JSON 对象 {站点列名: 精确值}；与 overview 同一口径"),
    severity: str = Query(None, description="Ticket Severity（P1~P4）；MTTR 趋势图下钻专用"),
    values: str = Query(None, description="多取值下钻（JSON 字符串数组）；里程碑阶段合计用"),
):
    """WO 明细下钻。过滤口径与 `/overview` 完全一致，否则行数对不上看板数字。

    ``values``：里程碑阶段合计下钻 —— 阶段是若干原始状态的合集，
    后端按 `IN (...)` 精确匹配，行数 = 各状态单数之和。
    """
    return wo_drilldown(
        dimension=dimension, value=value,
        time_start=time_start, time_end=time_end,
        region=region, adv=adv, severity=severity,
        values=values,
    )
