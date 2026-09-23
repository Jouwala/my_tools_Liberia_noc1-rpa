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

实现全部委托 `backend/services/eflow_flow.py`；本文件只做参数校验与路由。
只读：不对任何库表做写操作。
"""
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/eflow-flow", tags=["eflow-flow"])

_LANG_PATTERN = "^(zh|en)$"


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
