# -*- coding: utf-8 -*-
"""PM（预防性维护工单 PMT）执行与超期分析 API。

对应页面：前端「运维监控 / PM 执行分析」（`frontend/src/pages/PmExecutionAnalysis.tsx`）。

三个端点，全部只读：
  GET /api/pm-analysis/filters     筛选项（PM 计划 / 状态 / 站点 / 处理人 / 时间范围）
  GET /api/pm-analysis/overview    按 PM 计划 (pmp_no) 的聚合（KPI + 图表 + 表格）
  GET /api/pm-analysis/drilldown   明细下钻，卡片上的每个数字都能点进来

口径说明（字段语义陷阱、真实流程顺序、超期定义、下钻与概览如何保持一致）
统一写在 `backend/services/pm_caliber.py` 的模块 docstring —— 改口径只改那里。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Query

from backend.services import pm_analysis_service as svc

logger = logging.getLogger("pm_analysis")

router = APIRouter(prefix="/api/pm-analysis", tags=["pm-analysis"])


@router.get("/filters")
def filters():
    """筛选项。失败不抛 500，回一份空壳 + 默认窗口，保证页面能渲染出来。"""
    try:
        return svc.get_filters()
    except Exception as exc:  # noqa: BLE001
        logger.exception("[pm-analysis/filters] 失败: %s", exc)
        start, end = svc.default_window()
        return {
            "pmp_nos": [], "statuses": [], "sites": [], "handlers": [],
            "default_start": start, "default_end": end,
            "min_time": "", "max_time": "", "row_count": 0,
            "error": str(exc),
        }


@router.get("/overview")
def overview(
    start: str = Query("", description="起始日期 YYYY-MM-DD，空则用默认窗口"),
    end: str = Query("", description="结束日期 YYYY-MM-DD，空则用默认窗口"),
):
    """按 PM 计划 (pmp_no) 的执行与超期情况总览。"""
    try:
        return svc.build_overview(start, end)
    except Exception as exc:  # noqa: BLE001
        logger.exception("[pm-analysis/overview] 失败: %s", exc)
        return svc._empty_overview(  # noqa: SLF001 - 与服务层共用同一份空壳结构
            start, end, [f"数据加载失败: {exc}"]
        )


@router.get("/drilldown")
def drilldown(
    start: str = Query("", description="起始日期 YYYY-MM-DD"),
    end: str = Query("", description="结束日期 YYYY-MM-DD"),
    metric: str = Query(
        "total",
        description="下钻批次: total/closed/open/overdue/on_time/not_started/"
                    "closed_overdue/open_overdue/open_on_time",
    ),
    pmp_no: str = Query("", max_length=60, description="PM 计划号，空表示全部"),
    status: str = Query("", max_length=60, description="工单状态，空表示全部"),
    site_name: str = Query("", max_length=160, description="站点名，空表示全部"),
    handler: str = Query("", max_length=200, description="当前处理人，空表示全部"),
    month: str = Query("", max_length=7, description="生成月份 YYYY-MM，空表示全部"),
    limit: int = Query(svc.MAX_DETAIL_ROWS, ge=1, le=svc.MAX_DETAIL_ROWS,
                       description="取样上限，截断时 meta.warnings 会显式说明"),
):
    """下钻明细。

    ⚠️ metric 与各维度参数的组合必须与点击来源的卡片维度完全一致，
    否则明细行数与卡片数字对不上（见服务层 docstring）。
    """
    try:
        return svc.build_drilldown(start, end, metric=metric, pmp_no=pmp_no,
                                   status=status, site_name=site_name,
                                   handler=handler, month=month, limit=limit)
    except Exception as exc:  # noqa: BLE001
        logger.exception("[pm-analysis/drilldown] 失败: %s", exc)
        return {
            "meta": {"warnings": [f"数据加载失败: {exc}"], "metric": metric},
            "metric": metric, "pmp_no": pmp_no, "status": status,
            "site_name": site_name, "handler": handler, "month": month,
            "total": 0, "truncated": False,
            "rows": [], "columns": list(svc._DETAIL_COLUMNS),  # noqa: SLF001
        }
