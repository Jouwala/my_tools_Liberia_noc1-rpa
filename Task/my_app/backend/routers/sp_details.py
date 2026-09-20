"""SP 备件明细报表 API（SP_DETAILS_REPORT_V1）

服务页面 ``frontend/src/pages/SpDetailsReport.tsx``（``?page=sp_details``）。

数据来自任务 ``sp_email_details``（SP Spare Parts Details Report Email）每天
生成的合并工作簿 ``data/sp_email/data/SP Details Report <时间戳>.xlsx``
（sheet：Inventory / Inbound / Outbound / Transfer），口径见
``backend/services/sp_details_service.py`` 顶部 docstring —— 页面展示的与邮件
附件是**同一份文件**，不做二次加工。

端点：
- GET /api/sp-details/summary              统计卡片 + 各 sheet 元信息 + 数据来源
- GET /api/sp-details/rows                 某 sheet 的分页数据（筛选 / 排序 / 分页）
- GET /api/sp-details/filters              某 sheet 的筛选下拉候选值
- GET /api/sp-details/sources              数据源清单（排障用）

所有非法参数走「200 + warnings 软失败」，不抛 5xx：明细报表页面不应该因为一个
sheet 缺失或一个筛选值写错就整页打不开。
"""
import logging

from fastapi import APIRouter, Query

from backend.services import sp_details_service as svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sp-details", tags=["sp-details"])


@router.get("/summary")
def sp_details_summary():
    """统计卡片数据。

    返回 ``source``（合并文件名 / 生成时间 / 大小）、``overview``（总记录数、
    仓库数、未关闭单、物料种类、库存/入库/出库/调拨数量合计）与 ``sheets``
    （每个 sheet 的记录数、数量合计、未关闭数、状态/仓库/大类/业务类型分布）。
    """
    return svc.get_summary()


@router.get("/rows")
def sp_details_rows(
    sheet: str = Query(..., description="Inventory / Inbound / Outbound / Transfer"),
    page: int = Query(1, ge=1),
    page_size: int = Query(svc.DEFAULT_PAGE_SIZE, ge=1, le=svc.MAX_PAGE_SIZE),
    q: str = Query("", description="全列模糊搜索关键字"),
    sort: str = Query("", description="排序列名（必须是该 sheet 的真实列名）"),
    order: str = Query("asc", pattern="^(asc|desc)$"),
    filters: str = Query("", description='JSON 对象，如 {"Status":"Closed"}；值为数组时按 IN 处理'),
):
    """某 sheet 的分页明细。

    ``rows`` 是对象数组（键为**全部**列名，行详情弹窗直接用），``columns`` 为全列
    顺序，``numeric_columns`` 为数字列（前端右对齐 / 求和），``filtered_qty_total``
    是筛选后数量列合计（随搜索与筛选联动），``qty_total`` 是整表合计。
    """
    return svc.get_rows(
        sheet=sheet, page=page, page_size=page_size, q=q, sort=sort, order=order,
        filters=filters or None,
    )


@router.get("/filters")
def sp_details_filters(sheet: str = Query(..., description="Inventory / Inbound / Outbound / Transfer")):
    """某 sheet 的筛选下拉候选值（状态 / 仓库 / 物料大类 / 业务类型 / 域 / 物料状态）。"""
    return svc.get_filters(sheet)


@router.get("/sources")
def sp_details_sources():
    """数据源清单：当前用的是哪份合并文件、各 sheet 行数/列数。"""
    return {"sources": svc.get_sources()}
