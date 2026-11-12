# -*- coding: utf-8 -*-
"""eFlow 全流程查询 API
======================
用户输入**告警**（告警 ID / aid / 告警码）或 **TT 单号**，返回该单在 eFlow 里的
全流程图：规则驱动的状态机 + 该单实际走过的路径高亮。

- GET /api/eflow-flow/query?q=TT202609230060&lang=zh
      主查询。q 可以是 TT 单号 / 告警 ID / 告警码。
- GET /api/eflow-flow/graph?lang=zh
      仅返回规则骨架（不关联具体单子），供页面首屏先画出流程底图。
- GET /api/eflow-flow/rules?lang=zh
      规则清单（可按工单类型/规则类型过滤），供页面「规则明细」区块与导出。
- POST /api/eflow-flow/simulate?lang=zh
      多条件模拟：不查具体单子，按给定字段值（告警码 / VIP / HUB / 站点子类型
      / 下挂站点数等）评估全部规则，判定与 query 同引擎（eflow_flow_rules）。

实现全部委托 `backend/services/eflow_flow.py`；本文件只做参数校验与路由。
只读：不对任何库表做写操作。
"""
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/eflow-flow", tags=["eflow-flow"])

_LANG_PATTERN = "^(zh|en)$"

# 多条件模拟的合法字段（显式列出，避免依赖 pydantic 版本相关的内省 API）
_SIM_FIELDS = (
    "alarmCode", "vipSite", "hubSite", "siteSubType", "assetType",
    "netWorkType", "downSiteCount", "downstreamSites",
    "alarmDescription", "reasonType", "ticketSeverity",
)


class FlowSimulateIn(BaseModel):
    """多条件模拟入参：字段与规则条件引用的取值帧一一对应，全部可选。

    归一化（YES/NO→1/0、大小写、数值）由后端 build_value_frame 统一做，
    前端只传原始输入。
    """

    alarmCode: str = Field("", max_length=64, description="告警码，如 9995")
    vipSite: str = Field("", max_length=20, description="VIP 站点 YES/NO")
    hubSite: str = Field("", max_length=20, description="HUB 站点 YES/NO")
    siteSubType: str = Field("", max_length=40, description="站点子类型 REGULAR/ERA（eflow_site.sitesubtype）")
    assetType: str = Field("", max_length=40, description="站点类型 NORMAL/COOL（eflow_site.\"Site Type\"）")
    netWorkType: str = Field("", max_length=40, description="网络制式（eflow_tt.domain）")
    downSiteCount: str = Field("", max_length=20, description="当前故障下挂站点数（eflow_tt.down_site_count）")
    downstreamSites: str = Field("", max_length=20, description="站点下属站点总数（master_site_db.victims）")
    alarmDescription: str = Field("", max_length=200, description="告警描述（精确匹配）")
    reasonType: str = Field("", max_length=60, description="根因 POWER/MW/RAN…（eflow_tt.root_cause）")
    ticketSeverity: str = Field("", max_length=10, description="工单级别 P1..P4")


@router.get("/query")
def flow_query(
    q: str = Query(..., min_length=2, max_length=64,
                   description="TT 单号（TT202609230060）/ 告警 ID（1764213625912）/ 告警码（99933）"),
    lang: str = Query("zh", pattern=_LANG_PATTERN, description="zh=中文；en=英文"),
):
    """按告警或 TT 查询全流程。"""
    try:
        from backend.services.eflow_flow import query_flow
    except Exception as e:  # noqa: BLE001
        logger.exception("[eflow-flow] 模块导入失败")
        raise HTTPException(status_code=500, detail=f"流程模块不可用：{e}") from e

    try:
        return query_flow(q, lang=lang)
    except Exception as e:  # noqa: BLE001
        logger.exception("[eflow-flow] 查询失败 q=%s", q)
        raise HTTPException(status_code=500, detail=f"查询失败：{e}") from e


@router.get("/graph")
def flow_graph(lang: str = Query("zh", pattern=_LANG_PATTERN)):
    """规则驱动的流程骨架（节点 + 边），与具体单子无关。"""
    try:
        from backend.services.eflow_flow import build_flow_graph
        return build_flow_graph(lang=lang)
    except Exception as e:  # noqa: BLE001
        logger.exception("[eflow-flow] 骨架构建失败")
        raise HTTPException(status_code=500, detail=f"流程骨架构建失败：{e}") from e


@router.get("/rules")
def flow_rules(
    lang: str = Query("zh", pattern=_LANG_PATTERN),
    wo_type: Optional[str] = Query(None, description="按工单类型过滤，如 eflow-tt / eflow-wo"),
    rule_type: Optional[str] = Query(None, description="按规则类型过滤，如 ttPushOrderRule"),
):
    """规则清单（可选过滤），供页面展示与导出。"""
    try:
        from backend.database import get_raw_connection
        from backend.services.eflow_flow import _load_rules
        with get_raw_connection() as conn:
            rules = _load_rules(conn)
    except Exception as e:  # noqa: BLE001
        logger.exception("[eflow-flow] 规则读取失败")
        raise HTTPException(status_code=500, detail=f"规则读取失败：{e}") from e

    if wo_type:
        rules = [r for r in rules if r.get("wo_type") == wo_type]
    if rule_type:
        rules = [r for r in rules if r.get("rule_type") == rule_type]

    summary: Dict[str, Any] = {}
    for r in rules:
        k = r.get("rule_type") or "-"
        summary[k] = summary.get(k, 0) + 1

    return {"total": len(rules), "by_rule_type": summary, "rules": rules}


@router.post("/simulate")
def flow_simulate(body: FlowSimulateIn, lang: str = Query("zh", pattern=_LANG_PATTERN)):
    """多条件模拟：按给定字段值评估全部规则（不查具体单子）。

    判定与 /query 的规则标注同引擎同口径；全空条件视为误操作，返回 422。
    """
    conds = {k: getattr(body, k, "") for k in _SIM_FIELDS}
    if not any(str(v).strip() for v in conds.values()):
        raise HTTPException(status_code=422, detail="至少填写一个模拟条件")

    try:
        from backend.services.eflow_flow import simulate_flow
        return simulate_flow(conds, lang=lang)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        logger.exception("[eflow-flow] 多条件模拟失败")
        raise HTTPException(status_code=500, detail=f"模拟失败：{e}") from e
