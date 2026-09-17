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
    return await _forward_local_proxy(8790, request)


@router.api_route(
    "/api/realtime-proxy/fms",
    methods=["GET", "POST", "OPTIONS"],
    include_in_schema=False,
)
async def fms_proxy(request: Request):
    """同源转发到本机 FMS 实时代理 (127.0.0.1:8787)。

    根治：alarm-management.html 原本把实时拉取/健康检查写死成浏览器本机回环
    http://127.0.0.1:8787，远程访问 myapp 时该地址指向"访问者自己的电脑"，
    连不上服务器上的 FMS 代理，于是轮询永远失败并提示 Proxy not running。
    改为让浏览器打同源的 /api 路径，由后端再转发到服务器本机 127.0.0.1:8787。
    """
    return await _forward_local_proxy(8787, request)


async def _forward_local_proxy(port: int, request: Request) -> Response:
    """把同源 /api 请求原样转发到服务器本机实时代理 (127.0.0.1:<port>)/proxy。

    代理本身保持只绑回环（安全边界不变）；远程访问者经 myapp 后端中转，
    后端在本机访问代理，因此任何机器打开页面都能拿到实时数据。
    """
    # 把原始 query（含 url=编码后的目标 / cookie / method / body）原样拼到本机代理的 /proxy 上
    upstream = f"http://127.0.0.1:{port}/proxy?" + str(request.url.query)
    body = await request.body()
    fwd_headers = {}
    ct = request.headers.get("content-type")
    if ct:
        fwd_headers["Content-Type"] = ct
    # 透传调用方的 X-* 头：VMAX RDK 的 RSA 加密查询要求
    # X-Content-Type: application/x-vmax-s-rsa-encrypted，代理据此让服务端解密
    # {"param":{"encryptedStr":...}}（vreport report_query / export_data）。
    # 不回传/不透传 Host、Content-Length、Cookie 等由下游代理自己掌握的头。
    for name, value in request.headers.items():
        low = name.lower()
        if low.startswith("x-") and low not in ("x-forwarded-for", "x-forwarded-host",
                                                "x-forwarded-proto", "x-real-ip"):
            fwd_headers[name] = value
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
        logger.warning("[realtime-proxy] forward to 127.0.0.1:%s failed: %s", port, e)
        return Response(
            content=str(e).encode("utf-8"),
            status_code=502,
            headers={"Content-Type": "text/plain; charset=utf-8",
                     "Access-Control-Allow-Origin": "*"},
        )
