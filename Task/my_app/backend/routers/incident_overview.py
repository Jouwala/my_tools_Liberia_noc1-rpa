# -*- coding: utf-8 -*-
"""
事件总览（Incident Overview）API 路由
前缀: /api/incident-overview
"""
import logging

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from backend.services import incident_ai_service as ai_svc
from backend.services import incident_overview_service as svc

logger = logging.getLogger("incident_overview_router")

router = APIRouter(prefix="/api/incident-overview", tags=["incident-overview"])


@router.get("/all")
def get_all():
    try:
        return svc.get_all_data()
    except Exception as e:  # noqa: BLE001
        logger.exception("get_all 失败")
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/status")
def get_status():
    try:
        return svc.get_status_data()
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/tt-quality")
def get_tt_quality():
    try:
        return svc.get_tt_quality_data()
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/severity")
def get_severity():
    try:
        return svc.get_severity_data()
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/sla/{vendor}")
def get_sla(vendor: str):
    try:
        sheet = "ZTE" if vendor.lower() == "zte" else "3rd"
        return svc.get_sla_data(sheet)
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/details")
def get_details():
    try:
        det = svc.get_details_data()
        return {"data": det.get("data", []), "columns": det.get("columns", [])}
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/incident_log")
def get_incident_log(page: int = Query(1, ge=1), limit: int = Query(20, ge=1, le=100000),
                      download: bool = False):
    try:
        log = svc.get_incident_log_data()
        data = log.get("data", [])
        columns = log.get("columns", [])
        if download:
            return {"data": data, "columns": columns, "total": len(data), "page": 1, "limit": len(data)}
        total = len(data)
        start = (page - 1) * limit
        end = start + limit
        return {"data": data[start:end], "columns": columns,
                "total": total, "page": page, "limit": limit}
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/geojson")
def get_geojson():
    try:
        geo = svc.load_geojson()
        if geo is None:
            return JSONResponse(status_code=404, content={"error": "GeoJSON not found"})
        return JSONResponse(content=geo)
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.post("/ai/analyze")
async def ai_analyze(request: Request):
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    provider = body.get("provider", "local")
    api_key = body.get("api_key") or None
    base_url = body.get("base_url") or None
    model = body.get("model") or None
    prompt = body.get("prompt") or None
    lang = body.get("lang", "zh")
    context = body.get("context") or svc.get_all_data()
    return svc.analyze_with_ai(provider=provider, api_key=api_key, base_url=base_url,
                               model=model, prompt=prompt, lang=lang, context=context)


@router.post("/ai/{provider}")
async def ai_provider(provider: str, request: Request):
    """原版 6 个 /api/ai/<provider> 端点的等价实现。

    契约与 Unified_Tools/incident_overview/app.py 完全一致：
      入参 {api_key, prompt, data, stream, model} -> 出参 {analysis[, reasoning]}
    api_key 由前端界面填写并随请求传入，服务端不存储。
    注意：本路由必须声明在 /ai/analyze 之后，否则会把 analyze 当成 provider 吃掉。
    """
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}

    # DeepSeek 流式分支（原版默认 stream=True；前端固定传 false 走非流式）
    if provider == "deepseek" and body.get("stream"):
        api_key = body.get("api_key", "")
        if not api_key:
            return JSONResponse(status_code=400, content={"error": "API key required"})
        return StreamingResponse(
            ai_svc.stream_deepseek(api_key, body.get("prompt", "")),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    payload, status = ai_svc.dispatch(provider, body)
    if status != 200:
        logger.warning("AI provider %s 返回 %s: %s", provider, status, payload.get("error"))
    return JSONResponse(status_code=status, content=payload)


@router.post("/assistant/call")
async def assistant_call(request: Request):
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    return svc.assistant_call(phone=body.get("phone", ""), message=body.get("message", ""),
                              ticket=body.get("ticket"))


@router.post("/assistant/sms")
async def assistant_sms(request: Request):
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    return svc.assistant_sms(phone=body.get("phone", ""), message=body.get("message", ""),
                             ticket=body.get("ticket"))
