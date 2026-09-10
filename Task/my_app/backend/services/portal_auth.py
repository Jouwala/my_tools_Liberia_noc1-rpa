# -*- coding: utf-8 -*-
"""portal_auth.py - 适配 uniplam 门户用户鉴权的 myapp 会话模块
=============================================================

背景：my_app 自身没有用户鉴权系统，数据接口原本全开放。现在要求「用户在
uniplam 门户（http://<host>/uniplam/）登录后，从门户点开 myapp 看板深链
时免重复登录，且 myapp 对看板数据做强制鉴权（未登录 401）」。

uniplam 门户鉴权形态（见 D:/01_RPA/liberia-noc_soc-数据看板统一门户）：
- 登录后返回一个【内存 Bearer token】（64 hex 随机串，无 Cookie / JWT / 签名），
  浏览器存 localStorage，密钥 `liberia_noc_auth_v1`；
- 校验入口：`GET /uniplam/api/auth/me`，header `Authorization: Bearer <token>`
  返回 `{user}` 或 401；
- 会话只存在门户进程内存，myapp 无法离线验证，必须回调门户 `/me` 换取用户。

本模块职责：
1. `POST /api/auth/portal-login {token}`：把门户 token 回调给门户 `/me` 验证；
   成功后签发 myapp 自己的 HttpOnly 会话 Cookie（门户 token 只进门一次）。
2. `POST /api/auth/logout`：注销 myapp 会话。
3. `GET /api/auth/me`：返回当前会话用户（供前端引导/展示）。
4. `require_user` / `current_user`：供鉴权中间件/端点读取当前用户。

配置（环境变量）：
- UNIPLAM_ME_URL  门户 `/me` 回调整（默认 http://127.0.0.1:9267/uniplam/api/auth/me）
- UNIPLAM_TIMEOUT 回调超时秒（默认 5）
- MYAPP_SESSION_TTL    会话有效期秒（默认 8h）
- MYAPP_SESSION_COOKIE 会话 Cookie 名（默认 myapp_session）
"""
import logging
import os
import secrets
import threading
import time
import httpx
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from backend.security import client_is_local

logger = logging.getLogger(__name__)

UNIPLAM_ME_URL = os.environ.get("UNIPLAM_ME_URL", "http://127.0.0.1:9267/uniplam/api/auth/me")
UNIPLAM_TIMEOUT = float(os.environ.get("UNIPLAM_TIMEOUT", "5"))
SESSION_TTL = int(os.environ.get("MYAPP_SESSION_TTL", str(8 * 3600)))
SESSION_COOKIE = os.environ.get("MYAPP_SESSION_COOKIE", "myapp_session")

router = APIRouter(prefix="/api/auth", tags=["auth"])

# 进程内会话存储：sid -> {username, role, exp, allowedGroups, allowedCards, created}
_SESSIONS: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()


def _new_sid() -> str:
    return secrets.token_urlsafe(32)


def _now() -> float:
    return time.time()


def _prune():
    """清理过期会话（访问时顺带执行，避免专门起后台任务）。"""
    if not _SESSIONS:
        return
    cutoff = _now()
    expired = [sid for sid, s in _SESSIONS.items() if s.get("exp", 0) <= cutoff]
    for sid in expired:
        _SESSIONS.pop(sid, None)


async def verify_portal_token(portal_token: str) -> Optional[dict]:
    """回调 uniplam 门户 /me 验证门户 token，返回其返回的 {user}；失败返回 None。"""
    try:
        async with httpx.AsyncClient(timeout=UNIPLAM_TIMEOUT) as client:
            resp = await client.get(
                UNIPLAM_ME_URL,
                headers={"Authorization": f"Bearer {portal_token}"},
            )
        if resp.status_code != 200:
            logger.info("[portal-auth] uniplam /me 返回 %s", resp.status_code)
            return None
        data = resp.json()
        user = data.get("user") if isinstance(data, dict) else None
        return user if isinstance(user, dict) else None
    except Exception as exc:  # noqa: BLE001  网络/解析失败一律视为验证不通过
        logger.warning("[portal-auth] uniplam /me 调用失败: %s", exc)
        return None


def create_session(user: dict, response: Response) -> str:
    """为通过门户验证的用户建立 myapp 会话并种下 HttpOnly Cookie，返回 sid。"""
    sid = _new_sid()
    payload = {
        "username": user.get("username", user.get("id", "")),
        "role": user.get("role", "viewer"),
        "exp": _now() + SESSION_TTL,
        "created": _now(),
        "allowedGroups": user.get("allowedGroups"),
        "allowedCards": user.get("allowedCards"),
    }
    with _LOCK:
        _prune()
        _SESSIONS[sid] = payload
    response.set_cookie(
        key=SESSION_COOKIE,
        value=sid,
        max_age=SESSION_TTL,
        path="/",
        httponly=True,
        samesite="lax",
    )
    return sid


def destroy_session(request: Request, response: Response):
    """注销当前会话并清除 Cookie。"""
    sid = request.cookies.get(SESSION_COOKIE)
    if sid:
        with _LOCK:
            _SESSIONS.pop(sid, None)
    response.delete_cookie(key=SESSION_COOKIE, path="/")


def read_session(request: Request) -> Optional[dict]:
    """按 Cookie 取当前有效会话用户信息；不存在/过期返回 None。"""
    sid = request.cookies.get(SESSION_COOKIE)
    if not sid:
        return None
    with _LOCK:
        _prune()
        session = _SESSIONS.get(sid)
        if not session:
            return None
        if session.get("exp", 0) <= _now():
            _SESSIONS.pop(sid, None)
            return None
    return session


def current_user(request: Request) -> Optional[dict]:
    """给鉴权中间件/端点读当前用户；本机回环（内部脚本/调度）视为已授权并给占位身份。"""
    if client_is_local(request):
        return {"username": "local", "role": "admin"}
    return read_session(request)


def require_user(request: Request):
    """FastAPI 依赖：确保当前请求已登录（或本机），否则 401。"""
    user = current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="未登录：请通过统一门户登录")
    return user


@router.post("/portal-login")
async def portal_login(payload: dict, request: Request, response: Response):
    """用门户 token 换 myapp 会话 Cookie。"""
    if client_is_local(request):
        # 本机回环（前端同机、开发态）直接放行，避免本地开发被强制登录卡住
        sid = _new_sid()
        with _LOCK:
            _SESSIONS[sid] = {"username": "local", "role": "admin", "exp": _now() + SESSION_TTL}
        response.set_cookie(
            key=SESSION_COOKIE, value=sid, max_age=SESSION_TTL, path="/", httponly=True, samesite="lax")
        return {"user": {"username": "local", "role": "admin"}}

    token = payload.get("token")
    if not token or not isinstance(token, str):
        raise HTTPException(status_code=400, detail="缺少门户 token")
    user = await verify_portal_token(token)
    if user is None:
        raise HTTPException(status_code=401, detail="门户登录验证失败：请先在门户登录后重试")
    create_session(user, response)
    return {"user": user}


@router.post("/logout")
async def logout(request: Request, response: Response):
    destroy_session(request, response)
    return {"ok": True}


@router.get("/me")
async def me(request: Request):
    user = current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="未登录：请通过统一门户登录")
    return {"user": user}