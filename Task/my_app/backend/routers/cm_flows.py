"""RAN CM 流程/网元配置 API（Settings「任务配置」页签 -> 网元配置）

管理 cm_data_sync 的流程配置（new_url.txt / cm_flows.json）：
- GET  /api/cm-flows                    流程列表 + 每流程网元清单
- PUT  /api/cm-flows/{name}/ne-list     更新指定流程的网元清单
- GET  /api/cm-flows/export             全量导出（含 payload）
- POST /api/cm-flows/import             全量导入（整体替换，逐项校验）
"""
import logging

from fastapi import APIRouter, Depends, HTTPException

from backend.security import require_protected
from backend.services.cm_data import cm_data_export

logger = logging.getLogger(__name__)

router = APIRouter(tags=["cm-flows"])


@router.get("/api/cm-flows")
def cm_flows_get():
    """流程配置视图（页面展示/编辑用）"""
    try:
        return cm_data_export.get_cm_flow_config()
    except Exception as e:
        logger.warning(f"获取流程配置失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取流程配置失败: {e}")


@router.put("/api/cm-flows/{name}/ne-list", dependencies=[Depends(require_protected)])
def cm_flows_update(name: str, body: dict):
    """更新指定流程的网元清单 body: {"ne_list": ["SubNetwork=1,ManagedElement=3", ...]}"""
    res = cm_data_export.update_cm_flow_ne_list(name, body.get("ne_list"))
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error", "更新失败"))
    return res


@router.get("/api/cm-flows/export", dependencies=[Depends(require_protected)])
def cm_flows_export():
    """全量流程配置导出（JSON）"""
    return cm_data_export.export_cm_flow_config()


@router.post("/api/cm-flows/import", dependencies=[Depends(require_protected)])
def cm_flows_import(body: dict):
    """全量流程配置导入 body: {"flows": [{name, type, path, payload}, ...]}"""
    return cm_data_export.import_cm_flow_config(body.get("flows", []))
