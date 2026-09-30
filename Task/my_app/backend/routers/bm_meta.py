# -*- coding: utf-8 -*-
"""Meta 基准报告 API（ORANGE vs MTN 速率 PK + FDD 网络侧 KPI）。

口径见 `backend/services/bm_meta_caliber.py`（唯一真相源）。
本路由只做参数校验与错误兜底，**不写任何业务口径**。
"""
import logging
import re
from datetime import date

from fastapi import APIRouter, Query

from backend.services import bm_meta_caliber as cal
from backend.services import bm_meta_service as svc

logger = logging.getLogger("bm_meta")

router = APIRouter(prefix="/api/bm-meta", tags=["bm-meta"])

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _valid_date(v: str, fallback: str) -> str:
    """校验 YYYY-MM-DD 且必须是真实日期（`2026-02-31` 这种格式对但不存在的要挡掉）。"""
    if not v or not _DATE_RE.match(v):
        return fallback
    try:
        date.fromisoformat(v)
    except ValueError:
        return fallback
    return v


def _window(start: str, end: str) -> tuple[str, str]:
    """归一化时间窗：默认最近 365 天；start >= end 时回落默认窗口。

    默认 365 天而非 90 天 —— 理由见 `cal.default_window` 的 docstring：
    本表跨度 612 天，短期窗口会把长期趋势结论切掉。
    """
    d_start, d_end = cal.default_window(365)
    s = _valid_date(start, d_start)
    e = _valid_date(end, d_end)
    if s >= e:
        return d_start, d_end
    return s, e


def _metric(m: str, default: str = "speed") -> str:
    """指标 key 校验；非法则回落。本表 PK 指标只有 speed，故默认值即它。"""
    return m if m in cal.all_metrics() else default


def _empty_overview(start: str, end: str, msg: str) -> dict:
    """出错时的骨架返回：结构与正常一致，前端不会因缺字段而崩。"""
    return {
        "meta": {"start": start, "end": end, "brands": list(cal.BRANDS), "row_count": 0,
                 "data_min_date": None, "data_max_date": None,
                 "daily_total": 0, "daily_returned": 0, "daily_truncated": False,
                 "warnings": [msg]},
        "filters": {"min_date": None, "max_date": None, "row_count": 0, "brands": [], "metrics": []},
        "summary": {
            **{b: {"brand": b, "label": cal.BRAND_LABELS[b], "days": 0,
                   "speed": None, "speed_min": None, "speed_max": None} for b in cal.BRANDS},
            "network": {"days": 0},
        },
        "scores": {b: {"score": None, "parts": {}} for b in cal.BRANDS},
        "score_weights": cal.SCORE_WEIGHTS,
        "daily": [], "monthly": [],
        "wins": {"total_days": 0, "paired_days": 0, "ties": 0,
                 "orange_wins": 0, "mtn_wins": 0,
                 "orange_win_rate": None, "mtn_win_rate": None},
    }


@router.get("/filters")
def filters():
    """数据可用范围（时间跨度、两家标签、可下钻指标）。"""
    try:
        d_start, d_end = cal.default_window(365)
        data = svc.build_overview(*_window("", ""))["filters"]
        return {**data, "default_start": d_start, "default_end": d_end,
                "score_weights": cal.SCORE_WEIGHTS}
    except Exception as exc:
        logger.exception("[bm-meta/filters] failed: %s", exc)
        d_start, d_end = cal.default_window(365)
        return {"min_date": None, "max_date": None, "row_count": 0, "brands": [], "metrics": [],
                "default_start": d_start, "default_end": d_end,
                "score_weights": cal.SCORE_WEIGHTS, "error": str(exc)}


@router.get("/overview")
def overview(
    start: str = Query("", description="起始日 YYYY-MM-DD（含）"),
    end: str = Query("", description="结束日 YYYY-MM-DD（不含；前端传次日）"),
):
    """页面主接口：汇总卡 + 综合评分 + 逐日 PK + 网络侧 KPI + 月度对比 + 胜负统计。"""
    s, e = _window(start, end)
    try:
        return svc.build_overview(s, e)
    except Exception as exc:
        logger.exception("[bm-meta/overview] failed: %s", exc)
        return _empty_overview(s, e, f"数据加载失败: {exc}")


@router.get("/trend")
def trend(
    start: str = Query("", description="起始日 YYYY-MM-DD（含）"),
    end: str = Query("", description="结束日 YYYY-MM-DD（不含）"),
    metric: str = Query("speed", description="speed / bp / dl_throughput / dl_prb / ul_prb / traffic / rrc_users"),
    window: int = Query(7, ge=2, le=60, description="滚动均值窗口（天）"),
):
    """单指标趋势 + 滚动均值。指标非法时回落 speed。"""
    s, e = _window(start, end)
    metric = _metric(metric)
    try:
        return svc.build_trend(s, e, metric, window=window)
    except Exception as exc:
        logger.exception("[bm-meta/trend] failed: %s", exc)
        return {"meta": {"start": s, "end": e, "metric": metric,
                         "kind": cal.metric_meta(metric)["kind"],
                         "unit": cal.metric_meta(metric)["unit"],
                         "group": cal.metric_meta(metric)["group"],
                         "window": window, "points": 0,
                         "warnings": [f"数据加载失败: {exc}"]},
                "points": []}


@router.get("/drilldown")
def drilldown(
    start: str = Query("", description="起始日 YYYY-MM-DD（含）"),
    end: str = Query("", description="结束日 YYYY-MM-DD（不含）"),
    metric: str = Query("", description="配合 winner 使用，通常传 speed"),
    day: str = Query("", description="单日 YYYY-MM-DD"),
    winner: str = Query("", description="ORANGE / MTN：该指标下更强的一方"),
    limit: int = Query(500, ge=1, le=cal.MAX_DETAIL_ROWS),
):
    """明细下钻。

    `winner` 过滤返回「该指标胜者的那些天、且只含胜者自己的行」，
    使行数与该指标的胜场天数严格相等（与 `/overview` 的胜负统计同一套判定）。
    """
    s, e = _window(start, end)
    metric = _metric(metric, "")
    winner = winner if winner in cal.BRANDS else ""
    day = _valid_date(day, "")
    try:
        return svc.build_drilldown(s, e, metric=metric, day=day, winner=winner, limit=limit)
    except Exception as exc:
        logger.exception("[bm-meta/drilldown] failed: %s", exc)
        return {"meta": {"start": s, "end": e, "metric": metric or None, "day": day or None,
                         "winner": winner or None, "limit": limit,
                         "returned": 0, "truncated": False,
                         "warnings": [f"数据加载失败: {exc}"]},
                "rows": []}
