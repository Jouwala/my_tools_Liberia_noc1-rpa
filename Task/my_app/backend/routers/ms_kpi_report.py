"""MS Contract KPIs / WOs SLA 报表 API（MS_SLA_REPORT_WEB_V1）

服务两个页面：
- ``?page=ms_wo_sla``      MS WOs SLA Achievements Daily Report（kind=wo_sla）
- ``?page=ms_contract_kpi`` MS Contract KPIs & WOs Achievement Auto-Reports（kind=contract_kpi）

数据源：``data/ms_sla`` 下任务产出的两份报表工作簿本体 —— 与邮件附件是**同一份
文件**，页面不做二次加工；口径与解析细节见 ``backend/services/ms_kpi_report_service.py``
顶部 docstring（多层合并表头、目标行、PerSite 90% 占比口径等）。

端点（``kind`` 缺省 = wo_sla）：
- GET /api/ms-kpi-report/summary   统计卡片 + KPI 矩阵（表头/日行/月行/指标统计）+ 分表元信息
- GET /api/ms-kpi-report/rows      某 sheet 的分页数据（矩阵压平成「一行一天」）
- GET /api/ms-kpi-report/filters   某 sheet 的筛选下拉候选值（仅扁平表有配置）
- GET /api/ms-kpi-report/sources   数据源清单（排障用）

非法参数走「200 + warnings 软失败」，不抛 5xx；只有「整份工作簿都不存在」才 404
（此时页面确实无数据可展示，给出明确原因比返回空表更有用）。
"""
import logging

from fastapi import APIRouter, HTTPException, Query

from backend.services import ms_kpi_report_service as svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ms-kpi-report", tags=["ms-kpi-report"])

_KIND_DESC = "wo_sla | contract_kpi（缺省 wo_sla）"


@router.get("/summary")
def ms_kpi_report_summary(kind: str = Query(svc.DEFAULT_KIND, description=_KIND_DESC)):
    """统计卡片 + KPI 矩阵 + 分表元信息。

    ``overview`` 是达标概览（KPI 数 / 达标 / 未达标 / 天数 / 最需关注）；
    ``matrices`` 按 sheet 给出多层表头、日行、Month 汇总行与逐指标统计
    （目标值、方向、月值、达标天数、min/max/avg）。
    """
    try:
        return svc.get_summary(kind)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/rows")
def ms_kpi_report_rows(
    sheet: str = Query(..., description="sheet 名（见 /summary 的 sheets[].key）"),
    kind: str = Query(svc.DEFAULT_KIND, description=_KIND_DESC),
    page: int = Query(1, ge=1),
    page_size: int = Query(svc.DEFAULT_PAGE_SIZE, ge=1, le=svc.MAX_PAGE_SIZE),
    q: str = Query("", description="全列模糊搜索关键字"),
    sort: str = Query("", description="排序列名（必须是该 sheet 的真实列名）"),
    order: str = Query("asc", pattern="^(asc|desc)$"),
    filters: str = Query("", description='JSON 对象，如 {"Domain":"FO"}；值为数组时按 IN 处理'),
):
    """某 sheet 的分页明细（矩阵 sheet 会被压平成「一行一天」）。"""
    return svc.get_rows(
        kind=kind, sheet=sheet, page=page, page_size=page_size, q=q, sort=sort,
        order=order, filters=filters or None,
    )


@router.get("/filters")
def ms_kpi_report_filters(
    sheet: str = Query(..., description="sheet 名"),
    kind: str = Query(svc.DEFAULT_KIND, description=_KIND_DESC),
):
    """某 sheet 的筛选下拉候选值（FineBI 规划的 Domain/Priority、自动化报表的团队/频率 …）。"""
    return svc.get_filters(kind, sheet)


@router.get("/sources")
def ms_kpi_report_sources(kind: str = Query(svc.DEFAULT_KIND, description=_KIND_DESC)):
    """数据源清单：当前用的是哪份工作簿、各 sheet 行数/列数。"""
    try:
        return {"sources": svc.get_sources(kind)}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
