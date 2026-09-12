"""SP 物料统计汇总 API（RCK_MATERIAL_SUMMARY_V1）

从 routers/sp_dashboard.py 同源的 SP 体系里再拆一层，专门服务「WH/DOP 库存与消耗
汇总报表」页面（frontend/src/pages/SpMaterialSummary.tsx）。

端点：
- GET /api/sp-material/summary   汇总表（8 列 + Total 行）
- GET /api/sp-material/detail    单元格下钻明细

计算口径见 backend/services/sp_material_summary_service.py 顶部 docstring。
所有非法参数走「200 + warnings 软失败」，不抛 5xx（看板不能因为一个格子炸掉整页）。
"""
import logging

from fastapi import APIRouter

from backend.services.sp_material_summary_service import (
    get_material_detail,
    get_material_summary,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sp-material", tags=["sp-material-summary"])


@router.get("/summary")
def sp_material_summary(anchor_date: str | None = None, current_date: str | None = None):
    """WH/DOP 物料库存与消耗汇总表。

    RCK_MATERIAL_SUMMARY_V2
    - anchor_date: 期初锚点日 YYYY-MM-DD，缺省=当前快照所在自然月 1 号
    - current_date: 期末日 YYYY-MM-DD，缺省=库内 MAX(update_date)
    直接返回汇总对象本身（与 site_availability / ran_cells_kpi 同风格，不再包 status/data 壳）：
    rows（含 is_total 合计行；每行除库存列外还有 repair_outbound 与
    consumption_*_spare / consumption_*_cons 拆分列）、warnings、row_groups。
    """
    return get_material_summary(anchor_date, current_date)


@router.get("/detail")
def sp_material_detail(row_key: str, scope: str,
                       anchor_date: str | None = None,
                       current_date: str | None = None):
    """汇总表某格子的物料明细（数字下钻）。

    RCK_MATERIAL_SUMMARY_V2_DETAIL
    - row_key: 1st_wh / 2nd_wh / gbarnga_dop / kweaken_dop / others / total
    - scope:   anchor_spare_good | anchor_consumables | current_spare_good
               | current_consumables | need_repair
               | consumption_from_anchor_spare | consumption_from_anchor_cons
               | consumption_month_spare | consumption_month_cons
               | consumption_week_spare | consumption_week_cons
               | repair_outbound
      消耗类 scope 返回「期初 vs 期末逐物料对比」（Opening/Closing/Consumption Qty），
      repair_outbound 走 outband_details，其余走 inventory_details 快照。
    直接返回 {title, columns, data, warnings}。
    """
    return get_material_detail(row_key, scope, anchor_date, current_date)
