"""SP 备件 / 耗材汇总报表 API（SP_REPORT_WEB_V1）

服务两个页面：
- ``?page=sp_report``  SpareParts Inbound & Outbound & Inventory（kind=spareparts）
- ``?page=com_report`` Consumables Inbound & Outbound & Inventory（kind=consumables）

数据源：任务 ``sp_report_generate``（SP 备件报表生成，每天 05:15）产出的两份汇总
工作簿 ``data/sp_email/<前缀> <时间戳>.xlsx``（各含 Summary-Current /
Summary-Changed / Inbound / Outbound / Inventory 五张 sheet）—— 与邮件/WhatsApp
发出去的是**同一个文件**，页面不做二次加工。口径见
``backend/services/sp_report_service.py`` 顶部 docstring。

端点（``kind`` 缺省 = spareparts）：
- GET /api/sp-report/summary   统计卡片 + 各 sheet 元信息 + 每日矩阵 + 口径说明
- GET /api/sp-report/rows      某 sheet 的分页数据（筛选 / 排序 / 分页）
- GET /api/sp-report/filters   某 sheet 的筛选下拉候选值
- GET /api/sp-report/sources   数据源清单（排障用）

非法参数走「200 + warnings 软失败」，不抛 5xx；只有「整份工作簿都不存在」才 404
（此时页面确实无数据可展示，给出明确原因比返回空表更有用）。
"""
import logging

from fastapi import APIRouter, HTTPException, Query

from backend.services import sp_report_service as svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sp-report", tags=["sp-report"])

_KIND_DESC = "spareparts | consumables（缺省 spareparts）"


@router.get("/summary")
def sp_report_summary(kind: str = Query(svc.DEFAULT_KIND, description=_KIND_DESC)):
    """统计卡片数据。

    ``overview`` 取 Summary-Current 的 Total 行（入/出/库存/差异/补库量）与
    Alert Level / Remark 分布；``matrix`` 是 Summary-Changed 的「天 × 仓库」矩阵；
    ``notes`` 是报表自带的口径说明（原样透传，保证页面与 Excel 口径一致）。
    """
    try:
        return svc.get_summary(kind)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/rows")
def sp_report_rows(
    sheet: str = Query(..., description="Summary-Current / Summary-Changed / Inbound / Outbound / Inventory"),
    kind: str = Query(svc.DEFAULT_KIND, description=_KIND_DESC),
    page: int = Query(1, ge=1),
    page_size: int = Query(svc.DEFAULT_PAGE_SIZE, ge=1, le=svc.MAX_PAGE_SIZE),
    q: str = Query("", description="全列模糊搜索关键字"),
    sort: str = Query("", description="排序列名（必须是该 sheet 的真实列名）"),
    order: str = Query("asc", pattern="^(asc|desc)$"),
    filters: str = Query("", description='JSON 对象，如 {"Alert Level":"Urgent Replenish"}；值为数组时按 IN 处理'),
):
    """某 sheet 的分页明细（Summary-Changed 用 ``/summary`` 的 ``matrix`` 渲染，不走这里）。"""
    return svc.get_rows(
        kind=kind, sheet=sheet, page=page, page_size=page_size, q=q, sort=sort,
        order=order, filters=filters or None,
    )


@router.get("/filters")
def sp_report_filters(
    sheet: str = Query(..., description="sheet 名"),
    kind: str = Query(svc.DEFAULT_KIND, description=_KIND_DESC),
):
    """某 sheet 的筛选下拉候选值（状态 / 类型 / 仓库 / 专业域 / 告警级别 …）。"""
    return svc.get_filters(kind, sheet)


@router.get("/sources")
def sp_report_sources(kind: str = Query(svc.DEFAULT_KIND, description=_KIND_DESC)):
    """数据源清单：当前用的是哪份汇总工作簿、各 sheet 行数/列数。"""
    try:
        return {"sources": svc.get_sources(kind)}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
