"""实时代理控制 API —— 让前端「启用实时刷新」开关按需拉起/关闭本地代理。

端点（与前端 alarm-management.html 的「启用实时刷新」开关对接）：
- POST /api/realtime-proxy/start   确保两个本地代理(8787 FMS / 8790 VMAX)就绪并复用已有实例
- POST /api/realtime-proxy/stop    关闭两个本地代理
- GET  /api/realtime-proxy/status  返回各代理端口存活/健康状态

说明：代理是本地进程，浏览器无法直接 spawn，故由后端作为控制面。
代理以 DETACHED 方式拉起（见 backend.services.realtime_proxy_ctl），backend 重启不会误杀。
"""
import logging

import httpx
from fastapi import APIRouter, Request, Response

from backend.services import realtime_proxy_ctl as ctl

logger = logging.getLogger(__name__)

router = APIRouter(tags=["realtime-proxy"])


@router.post("/api/realtime-proxy/start")
def start_proxy():
    """按需拉起实时代理（8787 FMS / 8790 VMAX）。已运行则复用。"""
    results = ctl.ensure_all()
    logger.info("[realtime-proxy] start -> %s", results)
    return {"status": "ok", "proxies": results}


@router.post("/api/realtime-proxy/stop")
def stop_proxy():
    """关闭实时代理。"""
    results = ctl.kill_all()
    logger.info("[realtime-proxy] stop -> %s", results)
    return {"status": "ok", "proxies": results}


@router.get("/api/realtime-proxy/status")
def status_proxy():
    """返回两个代理的端口存活/健康状态。"""
    return {"status": "ok", "proxies": ctl.status_all()}


@router.api_route(
    "/api/realtime-proxy/cxo",
    methods=["GET", "POST", "OPTIONS"],
    include_in_schema=False,
)
async def cxo_proxy(request: Request):
    """同源转发到本机 VMAX 实时代理 (127.0.0.1:8790)。

    根治：cxo_dashboard.html 原本把实时拉取目标写死成浏览器本机回环
    http://127.0.0.1:8790，远程访问 myapp 时该地址指向"访问者自己的电脑"，
    连不上服务器上的 VMAX 代理，于是静默回退到快照并提示 offline/Failed to fetch。
    改为让浏览器打同源的 /api 路径，由后端再转发到服务器本机 127.0.0.1:8790，
    无论访问者从哪台机器打开页面都能拿到实时数据。
    """
    # 把原始 query（含 url=编码后的 VMAX 目标）原样拼到本机代理的 /proxy 上
    upstream = "http://127.0.0.1:8790/proxy?" + str(request.url.query)
    body = await request.body()
    fwd_headers = {}
    ct = request.headers.get("content-type")
    if ct:
        fwd_headers["Content-Type"] = ct
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.request(
                request.method,
                upstream,
                content=body if body else None,
                headers=fwd_headers,
            )
            return Response(
                content=resp.content,
                status_code=resp.status_code,
                headers={
                    "Content-Type": resp.headers.get("content-type", "application/json"),
                    "Access-Control-Allow-Origin": "*",
                },
            )
    except Exception as e:  # pragma: no cover - 上游代理不可用
        logger.warning("[realtime-proxy] cxo forward failed: %s", e)
        return Response(
            content=str(e).encode("utf-8"),
            status_code=502,
            headers={"Content-Type": "text/plain; charset=utf-8",
                     "Access-Control-Allow-Origin": "*"},
        )
