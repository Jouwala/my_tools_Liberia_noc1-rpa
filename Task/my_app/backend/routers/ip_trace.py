# -*- coding: utf-8 -*-
"""
IP 链路探测（IP Trace）API 路由
前缀: /api/ip-trace
注意：去掉了原 Flask 的 /shutdown（生命周期由 my_app 统一管理）
"""
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from backend.services import ip_trace_service as svc

logger = logging.getLogger("ip_trace_router")

router = APIRouter(prefix="/api/ip-trace", tags=["ip-trace"])


@router.post("/trace")
async def trace(request: Request):
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    target = body.get("target") or body.get("host")
    session_id = body.get("session_id")
    if not target:
        return JSONResponse(status_code=400, content={"error": "Target hostname is required"})
    try:
        return svc.start_trace(target, session_id)
    except Exception as e:  # noqa: BLE001
        logger.exception("start_trace 失败")
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.post("/stop")
async def stop(request: Request):
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    session_id = body.get("session_id")
    if not session_id:
        return JSONResponse(status_code=400, content={"error": "Session ID is required"})
    return svc.stop_trace(session_id)


@router.get("/status")
def status(session_id: str = ""):
    if not session_id:
        return JSONResponse(status_code=400, content={"error": "Session ID is required"})
    try:
        return svc.get_status(session_id)
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.post("/analyze")
async def analyze(request: Request):
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    session_id = body.get("session_id")
    if not session_id:
        return JSONResponse(status_code=400, content={"error": "Session ID is required"})
    try:
        hops, icmp_data, tcp_data, target = svc.build_analysis_payload(session_id)
        return svc.analyze_with_ai(
            hops, icmp_data, tcp_data, target,
            ai_provider=body.get("ai_provider", "local"),
            api_key=body.get("api_key"),
            lang=body.get("lang", "zh"),
            ai_model=body.get("ai_model"),
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("analyze 失败")
        return JSONResponse(status_code=500, content={"error": str(e)})
