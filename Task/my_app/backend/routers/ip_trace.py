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


async def _parse_body(request: Request) -> dict:
    """兼容解析请求体：前端 /trace、/stop 沿用 Flask 时代的 FormData（multipart），
    /analyze 等使用 JSON。先按 content-type 选择解析方式，失败时回退另一种。"""
    ctype = (request.headers.get("content-type") or "").lower()
    if ctype.startswith("multipart/form-data") or ctype.startswith("application/x-www-form-urlencoded"):
        try:
            form = await request.form()
            return {k: v for k, v in form.items()}
        except Exception:  # noqa: BLE001
            pass
    try:
        body = await request.json()
        if isinstance(body, dict):
            return body
    except Exception:  # noqa: BLE001
        # JSON 解析失败时再尝试按 form 解析（无 content-type 或异常格式）
        try:
            form = await request.form()
            return {k: v for k, v in form.items()}
        except Exception:  # noqa: BLE001
            pass
    return {}


def _get_session_id(body: dict, request: Request) -> str:
    """session_id 优先取请求体，回退到 X-Session-ID 请求头"""
    return body.get("session_id") or request.headers.get("X-Session-ID") or ""


@router.post("/trace")
async def trace(request: Request):
    body = await _parse_body(request)
    target = body.get("target") or body.get("host")
    session_id = _get_session_id(body, request)
    if not target:
        return JSONResponse(status_code=400, content={"error": "Target hostname is required"})
    try:
        return svc.start_trace(target, session_id or None)
    except Exception as e:  # noqa: BLE001
        logger.exception("start_trace 失败")
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.post("/stop")
async def stop(request: Request):
    body = await _parse_body(request)
    session_id = _get_session_id(body, request)
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
    body = await _parse_body(request)
    session_id = _get_session_id(body, request)
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
