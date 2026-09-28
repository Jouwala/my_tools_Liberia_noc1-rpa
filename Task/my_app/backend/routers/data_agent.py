# -*- coding: utf-8 -*-
"""
Data Agent 路由（只读 NL2SQL + 告警归因）

前缀: /api/data-agent

安全约定
--------
- api_key 由**前端请求体**传入，服务端不落盘、不写日志（沿用 `incident_ai_service.py` 约定）。
- 所有 SQL 经 `sql_guard.validate_sql()` 白名单校验后才落库执行。
- 本路由**不提供任何写接口**。
"""
import logging

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from backend.services import alarm_attribution_service as attrib
from backend.services import nl2sql_service as nl2sql

logger = logging.getLogger("data_agent_router")

router = APIRouter(prefix="/api/data-agent", tags=["data-agent"])


class AskIn(BaseModel):
    question: str = ""
    provider: str = ""
    api_key: str = ""
    model: str = ""
    base_url: str = ""
    run: bool = True
    # sql 非空 = 用户手改 SQL 后重跑（跳过生成）
    sql: str = ""
    history: list = []


class AttributeIn(BaseModel):
    site: str = ""
    days: int = 7
    provider: str = "local"
    api_key: str = ""
    model: str = ""
    base_url: str = ""
    lang: str = "zh"


@router.get("/schema")
def get_schema():
    """返回可查询的表清单（供前端做提示与校验，也是模型白名单的来源）。"""
    try:
        desc, tables = nl2sql.build_schema_context()
        return {"tables": tables, "table_count": len(tables), "schema": desc}
    except Exception as e:  # noqa: BLE001
        logger.exception("get_schema 失败")
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.post("/ask")
def ask(body: AskIn):
    """自然语言 → 只读 SQL → 结果。

    失败一律返回可读的中文原因（400/500），不抛栈给前端。
    """
    try:
        result = nl2sql.ask(
            question=body.question,
            provider=body.provider,
            api_key=body.api_key,
            model=body.model,
            base_url=body.base_url,
            run=body.run,
            sql=body.sql,
            history=body.history,
        )
        return result
    except nl2sql.Nl2SqlError as e:
        # 护栏拒绝 / 模型无法回答 —— 属于预期内的用户可见错误
        return JSONResponse(status_code=400, content={"error": str(e)})
    except Exception as e:  # noqa: BLE001
        logger.exception("ask 失败")
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.post("/attribute")
def attribute(body: AttributeIn):
    """告警归因：客观统计 + AI 解读（AI 不可用时降级本地规则）。"""
    try:
        return attrib.attribute(
            site=(body.site or "").strip() or None,
            days=body.days,
            provider=body.provider,
            api_key=body.api_key,
            model=body.model,
            base_url=body.base_url,
            lang=body.lang,
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("attribute 失败")
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/sites")
def get_sites(limit: int = Query(50, ge=1, le=200)):
    """站点建议清单（供归因页下拉），取自活跃告警与历史告警。"""
    try:
        import backend.services.alarm_attribution_service as svc
        from backend.database import get_raw_connection
        names = []
        with get_raw_connection() as conn:
            for tbl in ("realtime_alarm", "history_alarm"):
                if not svc._table_exists(conn, tbl):
                    continue
                try:
                    rows = svc._q(
                        conn,
                        f'SELECT site_name, COUNT(*) AS c FROM "{tbl}" '
                        f"WHERE site_name IS NOT NULL AND site_name <> '' "
                        f"GROUP BY site_name ORDER BY c DESC LIMIT ?",
                        [limit],
                    )
                except Exception:  # noqa: BLE001
                    continue
                for r in rows:
                    n = (r.get("site_name") or "").strip()
                    if n and n not in names:
                        names.append(n)
            conn.close()
        return {"sites": names[:limit]}
    except Exception as e:  # noqa: BLE001
        logger.exception("get_sites 失败")
        return JSONResponse(status_code=500, content={"error": str(e)})
