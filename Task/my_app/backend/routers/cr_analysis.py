# -*- coding: utf-8 -*-
"""CR（变更请求）按 change_category 的计划 / 完成情况分析 API。

对应页面：前端「变更管理 / CR 变更分析」（`frontend/src/pages/CrChangeAnalysis.tsx`）。

端点为**只读**，共 5 个：
  GET /api/cr-analysis/filters             筛选项（类别 / 子类别 / 状态 / 数据时间范围）
  GET /api/cr-analysis/overview            按 change_category 的聚合（KPI + 图表 + 表格数据）
  GET /api/cr-analysis/drilldown           明细下钻，卡片上的每个数字都能点进来
  GET /api/cr-analysis/workflow            审批流程各步骤的到达量与停留耗时
  GET /api/cr-analysis/workflow-drilldown  步骤下钻（走过 / 当前停在某一步的 CR）

口径说明（终态、按时/延期判定、下钻与概览如何保持一致）统一写在
`backend/services/cr_analysis_service.py` 的模块 docstring —— 改口径只改那里。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Query

from backend.services import cr_analysis_service as svc
from backend.services import cr_workflow_service as wfs

logger = logging.getLogger("cr_analysis")

router = APIRouter(prefix="/api/cr-analysis", tags=["cr-analysis"])


@router.get("/filters")
def filters():
    """筛选项。失败不抛 500，回一份空壳 + 默认窗口，保证页面能渲染出来。"""
    try:
        return svc.get_filters()
    except Exception as exc:  # noqa: BLE001
        logger.exception("[cr-analysis/filters] 失败: %s", exc)
        start, end = svc.default_window()
        return {
            "categories": [], "sub_categories": [], "statuses": [],
            "default_start": start, "default_end": end,
            "min_time": "", "max_time": "", "row_count": 0,
            "error": str(exc),
        }


@router.get("/overview")
def overview(
    start: str = Query("", description="起始日期 YYYY-MM-DD，空则用默认窗口"),
    end: str = Query("", description="结束日期 YYYY-MM-DD，空则用默认窗口"),
):
    """按 change_category 的计划 / 完成情况总览。"""
    try:
        return svc.build_overview(start, end)
    except Exception as exc:  # noqa: BLE001
        logger.exception("[cr-analysis/overview] 失败: %s", exc)
        return svc._empty_overview(  # noqa: SLF001 - 与服务层共用同一份空壳结构
            start, end, [f"load_failed: {exc}"]
        )


@router.get("/drilldown")
def drilldown(
    start: str = Query("", description="起始日期 YYYY-MM-DD"),
    end: str = Query("", description="结束日期 YYYY-MM-DD"),
    metric: str = Query(
        "total",
        description="下钻批次: total/planned/executed/unexecuted/on_time/delayed/"
                    "closed/open/canceled/status（status 时须给 status 参数）",
    ),
    category: str = Query("", max_length=120, description="change_category，空表示全部"),
    sub_category: str = Query("", max_length=160, description="子类别，空表示全部"),
    month: str = Query("", max_length=7, description="登记月份 YYYY-MM，空表示全部"),
    status: str = Query(
        "", max_length=80,
        description="状态名（metric=status 时使用）；大小写与首尾空格由服务端归一",
    ),
    limit: int = Query(svc.MAX_DETAIL_ROWS, ge=1, le=svc.MAX_DETAIL_ROWS,
                       description="取样上限，截断时 meta.warnings 会显式说明"),
):
    """下钻明细。

    ⚠️ metric / category / sub_category / month / status 的组合必须与点击
    来源的卡片维度完全一致，否则明细行数与卡片数字对不上（见服务层 docstring）。
    """
    try:
        return svc.build_drilldown(start, end, metric=metric, category=category,
                                   sub_category=sub_category, month=month,
                                   status=status, limit=limit)
    except Exception as exc:  # noqa: BLE001
        logger.exception("[cr-analysis/drilldown] 失败: %s", exc)
        return {
            "meta": {"warnings": [f"load_failed: {exc}"], "metric": metric},
            "metric": metric, "category": category, "sub_category": sub_category,
            "month": month, "status": status, "total": 0, "truncated": False,
            "rows": [], "columns": list(svc._DETAIL_COLUMNS),  # noqa: SLF001
        }


@router.get("/workflow")
def workflow(
    start: str = Query("", description="起始日期 YYYY-MM-DD"),
    end: str = Query("", description="结束日期 YYYY-MM-DD"),
):
    """审批流程各步骤的到达量与停留耗时。

    ⚠️ 步骤顺序是 `cr_caliber.WORKFLOW_STEPS` 的**真实时序**，不是列名字母序。
    """
    try:
        return wfs.build_workflow(start, end)
    except Exception as exc:  # noqa: BLE001
        logger.exception("[cr-analysis/workflow] 失败: %s", exc)
        return {
            "meta": {"warnings": [f"load_failed: {exc}"]},
            "steps": [], "rejected": 0, "total": 0,
        }


@router.get("/workflow-drilldown")
def workflow_drilldown(
    start: str = Query("", description="起始日期 YYYY-MM-DD"),
    end: str = Query("", description="结束日期 YYYY-MM-DD"),
    step: str = Query("", max_length=32, description="步骤 key，见 cr_caliber.WORKFLOW_STEPS"),
    kind: str = Query("arrived", description="arrived=走过该步 / current=当前停在该步"),
    status: str = Query("", max_length=80, description="叠加的状态过滤，空表示全部"),
    limit: int = Query(svc.MAX_DETAIL_ROWS, ge=1, le=svc.MAX_DETAIL_ROWS,
                       description="取样上限，截断时 meta.warnings 会显式说明"),
):
    """步骤下钻：走过 / 停在该步的 CR，按停留天数倒序。"""
    try:
        return wfs.drill_workflow(start, end, step=step, kind=kind,
                                  status=status, limit=limit)
    except Exception as exc:  # noqa: BLE001
        logger.exception("[cr-analysis/workflow-drilldown] 失败: %s", exc)
        return {
            "meta": {"warnings": [f"load_failed: {exc}"], "step": step},
            "step": step, "kind": kind, "status": status,
            "total": 0, "truncated": False, "rows": [],
        }
