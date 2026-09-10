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
import threading
import time
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from backend.services import portal_login_service as svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/portals", tags=["portals"])


class PortalLoginRequest(BaseModel):
    system: str
    browser: str | None = None  # "default" 或具体 exe 路径；缺省用默认浏览器


class PortalCloseRequest(BaseModel):
    system: str


@router.get("")
def get_portals():
    """列出全部可登录门户。"""
    return {"portals": svc.list_portals()}


@router.post("/login")
def login_portal(body: PortalLoginRequest):
    """触发一键登录：后台线程启动浏览器并自动填充凭据，立即返回 job_id 供前端轮询。"""
    if body.system not in svc.PORTALS:
        raise HTTPException(status_code=400, detail=f"未知门户: {body.system}")
    job_id = _spawn(body.system, body.browser)
    return {"status": "launching", "job_id": job_id, "system": body.system}


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
def login_status(job_id: str):
    """查询某次登录任务的状态。"""
    with svc.JOBS_LOCK:
        j = svc.JOBS.get(job_id)
    if not j:
        return {"job_id": job_id, "state": "unknown", "message": "未找到该任务（可能已过期）"}
    return {
        "job_id": job_id,
        "system": j.get("system"),
        "state": j.get("state"),
        "message": j.get("message"),
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
