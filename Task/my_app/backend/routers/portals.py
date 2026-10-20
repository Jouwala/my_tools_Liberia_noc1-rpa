"""
portals.py - 一键门户登录 API
============================
让前端「门户登录」页调用，用本机默认浏览器打开对应系统并自动登录。

端点：
- GET  /api/portals                  列出全部门户（含 host/port/是否已登录）
- POST /api/portals/login             触发登录：body {system, browser?} -> {job_id}
- GET  /api/portals/login/status      轮询：?job_id= -> 当前任务状态
- POST /api/portals/close             关闭常驻浏览器：body {system}
"""
import logging
import secrets
import threading
import time
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

from backend.services import portal_login_service as svc
from backend.api_i18n import translate_text

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/portals", tags=["portals"])


class PortalLoginRequest(BaseModel):
    system: str
    browser: str | None = None  # "default" 或具体 exe 路径；缺省用默认浏览器


class PortalCloseRequest(BaseModel):
    system: str


class PortalClientTicketRequest(BaseModel):
    system: str


class PortalClientConsumeRequest(BaseModel):
    ticket: str


# 浏览器扩展拿不到 my_app 页面的 HttpOnly 会话 Cookie 是正常的；所以前端先在
# 同源已登录会话下申请一张短票据，扩展再一次性消费它。票据不包含凭据，也不出现在 URL。
_CLIENT_TICKET_TTL_SECONDS = 45
_CLIENT_TICKETS: dict[str, dict] = {}
_CLIENT_TICKETS_LOCK = threading.Lock()


def _purge_client_tickets(now: float) -> None:
    expired = [key for key, item in _CLIENT_TICKETS.items()
               if item.get("expires_at", 0) <= now]
    for key in expired:
        _CLIENT_TICKETS.pop(key, None)


@router.get("")
def get_portals(request: Request):
    """列出全部可登录门户。

    RCK_PORTALS_V2_RAIS：门户表已含 RAIS（10.100.20.9:8766，直接鉴权登录）。
    RCK_PORTALS_V3_LOCAL：额外返回 `client_is_local`（访问者是否就在 my_app 服务器本机），
    供前端判断「直连门户（eFlow/RAIS）能否直接用服务器端直接鉴权登录」。
    """
    ip = request.client.host if request.client else None
    return {"portals": svc.list_portals(), "client_is_local": svc.client_is_local(ip)}


@router.post("/login")
def login_portal(body: PortalLoginRequest):
    """触发一键登录：后台线程启动浏览器并自动填充凭据，立即返回 job_id 供前端轮询。"""
    if body.system not in svc.PORTALS:
        raise HTTPException(status_code=400, detail=f"未知门户: {body.system}")
    job_id = _spawn(body.system, body.browser)
    return {"status": "launching", "job_id": job_id, "system": body.system}


@router.post("/client-login/ticket")
def create_client_login_ticket(body: PortalClientTicketRequest):
    """为直连门户签发客户端扩展的一次性登录票据。

    正常 API 鉴权中间件会保护本接口；扩展只可拿这张随机票据换取一次会话计划。

    ⚠️ 判定依据必须是「该门户是否 direct」（即前端会走扩展种 Cookie 的那条路），
    不能写死 `("eflow", "rais")` —— 后端 PORTALS 新增直连门户时（如 battery_ume），
    写死的白名单会让前端拿到 400「该门户不支持客户端会话登录」。
    """
    spec = svc.PORTALS.get(body.system)
    if spec is None:
        raise HTTPException(status_code=400, detail=f"未知门户: {body.system}")
    if not spec.get("direct"):
        raise HTTPException(status_code=400, detail="该门户不支持客户端会话登录")
    now = time.monotonic()
    ticket = secrets.token_urlsafe(32)
    with _CLIENT_TICKETS_LOCK:
        _purge_client_tickets(now)
        _CLIENT_TICKETS[ticket] = {
            "system": body.system,
            "expires_at": now + _CLIENT_TICKET_TTL_SECONDS,
        }
    return {"ticket": ticket, "expires_in": _CLIENT_TICKET_TTL_SECONDS}


@router.post("/client-login/consume")
def consume_client_login_ticket(body: PortalClientConsumeRequest):
    """由受管扩展一次性消费短票据，返回不含账号密码的会话写入计划。"""
    now = time.monotonic()
    with _CLIENT_TICKETS_LOCK:
        _purge_client_tickets(now)
        item = _CLIENT_TICKETS.pop(body.ticket, None)
    if not item:
        raise HTTPException(status_code=401, detail="登录票据无效或已过期")
    try:
        plan = svc.build_client_login_plan(item["system"])
    except Exception as exc:  # noqa: BLE001 - 上游鉴权失败须转换为安全的 API 错误
        logger.warning("[PORTAL] 构造客户端 %s 会话计划失败: %s", item["system"], type(exc).__name__)
        raise HTTPException(status_code=502, detail="门户会话获取失败，请稍后重试") from exc
    return {"plan": plan}


def _spawn(system: str, browser: str | None) -> str:
    # 预先生成 job_id 并占位写入 JOBS，立即返回给前端轮询。
    # 关键：绝不能等 launch_and_login 的返回值——那要等整个浏览器拉起+登录
    # 跑完（几十秒），5 秒内拿不到就会返回伪造 uuid，导致前端轮询
    # "未找到该任务（可能已过期）" 且一直 loading。
    job_id = uuid.uuid4().hex[:12]
    svc._job_update(job_id, system=system, state="launching",
                   message="正在启动浏览器...", log=[], start=time.time())

    def _run():
        try:
            # eFlow 走「直接鉴权」登录：复用 auth_manager 复刻 RSA+OAuth2 拿会话，
            # 再 CDP 种 cookie 打开已登录主页，绕开登录页 DOM 依赖与 anti-debugger。
            # 仅对 eflow 生效，其余门户仍走原 launch_and_login（填表）路径，零改动。
            if system == "eflow":
                svc.launch_and_login_eflow_direct(system, browser, job_id=job_id)
            elif system == "rais":
                # RAIS 同为「直接鉴权」：AES-256-CBC 加密密码 POST verify4web.serv 换 SSO token，
                # 再 CDP 种 cookie（RAIS_PORTALSSOCookie 等）打开已登录主页。
                svc.launch_and_login_rais_direct(system, browser, job_id=job_id)
            else:
                svc.launch_and_login(system, browser, job_id=job_id)
        except Exception as e:  # pragma: no cover
            logger.warning(f"[PORTAL] 线程异常 {system}: {e}", exc_info=True)
            svc._job_update(job_id, state="failed",
                           message=f"异常: {type(e).__name__}: {e}", end=time.time())

    t = threading.Thread(target=_run, daemon=False)
    t.start()
    return job_id


@router.get("/login/status")
def login_status(request: Request, job_id: str):
    """查询某次登录任务的状态。

    message 是给人看的句子，走 api_i18n 按请求语言翻译；state 是前端匹配用的码，不动。
    """
    with svc.JOBS_LOCK:
        j = svc.JOBS.get(job_id)
    if not j:
        return {"job_id": job_id, "state": "unknown",
                "message": translate_text("未找到该任务（可能已过期）", request)}
    return {
        "job_id": job_id,
        "system": j.get("system"),
        "state": j.get("state"),
        "message": translate_text(j.get("message"), request),
        "log": j.get("log", []),
        "start": j.get("start"),
        "end": j.get("end"),
    }


@router.post("/close")
def close_portal(body: PortalCloseRequest):
    """关闭某门户的常驻浏览器会话。"""
    if body.system not in svc.PORTALS:
        raise HTTPException(status_code=400, detail=f"未知门户: {body.system}")
    closed = svc.close_session(body.system)
    return {"status": "ok", "system": body.system, "closed": closed}


@router.get("/inject.js")
def portal_inject_js(system: str):
    """客户端本机登录用的自动填表脚本（由 nginx 反代页注入，同源加载）。

    凭据随本次请求下发（脚本内嵌，no-store 不缓存），不单独暴露明文接口。
    注意：任何能访问 my_app 的客户端都能拿到共享账号 —— 与既有的
    「服务器代登录」暴露面一致，仅在内网使用。
    """
    if system not in svc.PORTALS:
        raise HTTPException(status_code=400, detail=f"未知门户: {system}")
    if system not in svc.PROXY_PREFIXES:
        raise HTTPException(status_code=404, detail=f"门户 {system} 未配置 nginx 反代")
    try:
        user, pwd = svc._creds(svc.PORTALS[system]["cred_key"])
    except Exception as e:  # pragma: no cover
        logger.warning(f"[PORTAL] 读取凭据失败 {system}: {e}")
        raise HTTPException(status_code=500, detail=f"读取凭据失败: {e}")
    js = svc.build_inject_js(system, user, pwd)
    return Response(
        content=js,
        media_type="application/javascript; charset=utf-8",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )
