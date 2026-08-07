"""SP 备件仓库看板 API —— 从 main.py 拆分（架构优化 Phase 1）

迁移端点（路径与返回结构与迁移前完全一致，前端零改动）：
- /api/sp-data/summary、/api/sp-data/rows       SP 表概览与分页查询
- /api/data、/api/warehouses、/api/details      仓库看板（对齐 Unified_Tools/WareHouseDashBoard）

计算逻辑完整复用 app_sp_optimized.py（见 backend/services/sp_dashboard.py），
返回结构对齐参考 Flask 的 /api/data、/api/warehouses、/api/details。
"""
import logging

from fastapi import APIRouter, HTTPException

from backend.services.sp_dashboard import (
    get_dashboard_data,
    get_warehouses as sp_list_warehouses,
    get_detail_rows,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["sp-dashboard"])


@router.get("/api/sp-data/summary")
def sp_data_summary():
    """各 SP 表的总行数、列、最近同步时间、衍生指标（供仓库看板）"""
    from backend.services.get_sp_table import get_sp_summary
    return get_sp_summary()


@router.get("/api/sp-data/rows")
def sp_data_rows(table: str, page: int = 1, size: int = 50, search: str = ""):
    """分页 + 模糊搜索返回某 SP 表的数据"""
    from backend.services.get_sp_table import get_sp_rows, SP_TABLES
    if table not in SP_TABLES:
        raise HTTPException(status_code=400, detail=f"未知表: {table}")
    return get_sp_rows(table, page=page, size=size, search=search)


@router.get("/api/data")
def sp_dashboard_data(date_start: str | None = None, date_end: str | None = None,
                      warehouse: str | None = None):
    """仓库看板主数据，结构对齐参考 Flask /api/data。"""
    data = get_dashboard_data(date_start, date_end, warehouse)
    return {"status": "success", "data": data}


@router.get("/api/warehouses")
def sp_dashboard_warehouses():
    """仓库下拉列表。"""
    return {"status": "success", "warehouses": sp_list_warehouses()}


@router.get("/api/details")
def sp_dashboard_details(
    type: str,
    column: str | None = None,
    value: str | None = None,
    mode: str = "exact",
    first_column: str | None = None,
    first_value: str | None = None,
    date_start: str | None = None,
    date_end: str | None = None,
    warehouse: str | None = None,
    status_column: str | None = None,
    status_value: str | None = None,
    status_mode: str = "exact",
    sla_filter: bool = False,
    sla_type: str | None = None,
):
    """明细查询，对齐参考 Flask /api/details。"""
    if type not in ("inband", "outband", "inventory"):
        raise HTTPException(status_code=400, detail=f"未知明细类型: {type}")
    result = get_detail_rows(
        detail_type=type,
        filter_column=column,
        filter_value=value,
        filter_mode=mode,
        first_column=first_column,
        first_value=first_value,
        date_start=date_start,
        date_end=date_end,
        warehouse=warehouse,
        status_column=status_column,
        status_value=status_value,
        status_mode=status_mode,
        sla_filter=sla_filter,
        sla_type=sla_type,
    )
    return {"status": "success", **result}
