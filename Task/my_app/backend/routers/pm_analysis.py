# -*- coding: utf-8 -*-
"""PM（预防性维护工单 PMT）执行与超期分析 API。

对应页面：前端「运维监控 / PM 执行分析」（`frontend/src/pages/PmExecutionAnalysis.tsx`）。

五个端点，全部只读：
  GET /api/pm-analysis/filters            筛选项（PM 计划 / 状态 / 站点 / 处理人 / 时间范围）
  GET /api/pm-analysis/overview           按 PM 计划 (pmp_no) 的聚合（KPI + 图表 + 表格）
  GET /api/pm-analysis/drilldown          明细下钻，卡片上的每个数字都能点进来
  GET /api/pm-analysis/workflow           里程碑到达量 / 滞留量 / 各环节停留耗时
  GET /api/pm-analysis/workflow-drilldown 里程碑下钻（走过 / 当前停在该节点）

口径说明（字段语义陷阱、超期定义、下钻与概览如何保持一致）
统一写在 `backend/services/pm_caliber.py` 的模块 docstring —— 改口径只改那里。
里程碑顺序严格按 eFlow 的 Workflow History（`queryAllSteps`，payload
`eflow-pm-task`）：Create → Schedule → Accept → Process → PMManagerApprove
→ FLMLeaderApprove → Closed（**与 pm_caliber 里的「真实时序」相反**，见
`backend/services/pm_workflow_service.py` 的模块 docstring）。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Query

from backend.services import pm_analysis_service as svc
from backend.services import pm_workflow_service as wfs

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


@router.get("/workflow")
def workflow(
    start: str = Query("", description="起始日期 YYYY-MM-DD"),
    end: str = Query("", description="结束日期 YYYY-MM-DD"),
    pmp_no: str = Query("", max_length=60, description="PM 计划号，空表示全部"),
):
    """里程碑到达量 / 滞留量 / 各环节停留耗时。

    ⚠️ 顺序按 eFlow Workflow History：Create → Schedule → Accept → Process
    → PM Manager Approve → FLM Leader Approve → Closed。
    `pmp_no` 与概览的计划筛选同口径（都走 `pm_caliber.base_where`），
    前端的计划号前端筛选会把它透传过来，保证里程碑与 KPI 用同一批工单。
    """
    try:
        return wfs.build_workflow(start, end, pmp_no=pmp_no)
    except Exception as exc:  # noqa: BLE001
        logger.exception("[pm-analysis/workflow] 失败: %s", exc)
        return {
            "meta": {"warnings": [f"数据加载失败: {exc}"], "pmp_no": pmp_no},
            "milestones": [], "total": 0, "closed": 0, "in_flight": 0,
        }


@router.get("/workflow-drilldown")
def workflow_drilldown(
    start: str = Query("", description="起始日期 YYYY-MM-DD"),
    end: str = Query("", description="结束日期 YYYY-MM-DD"),
    key: str = Query(
        "", max_length=32,
        description="里程碑 key：created/scheduled/accepted/processed/"
                    "pm_approved/flm_approved/closed",
    ),
    kind: str = Query(
        "arrived",
        description="arrived=走过该里程碑 / current=当前停在该里程碑 / done=已关闭（仅 closed）",
    ),
    pmp_no: str = Query("", max_length=60, description="PM 计划号，空表示全部"),
    limit: int = Query(svc.MAX_DETAIL_ROWS, ge=1, le=svc.MAX_DETAIL_ROWS,
                       description="取样上限，截断时 meta.warnings 会显式说明"),
):
    """里程碑下钻：走过 / 停在该节点的 PMT，按停留天数倒序。"""
    try:
        return wfs.drill_workflow(start, end, key=key, kind=kind,
                                  pmp_no=pmp_no, limit=limit)
    except Exception as exc:  # noqa: BLE001
        logger.exception("[pm-analysis/workflow-drilldown] 失败: %s", exc)
        return {
            "meta": {"warnings": [f"数据加载失败: {exc}"], "key": key},
            "key": key, "kind": kind, "pmp_no": pmp_no,
            "total": 0, "truncated": False, "rows": [],
        }
