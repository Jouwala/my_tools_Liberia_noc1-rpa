"""
credentials.py - 凭据管理 API 路由
==================================
提供"设置"页面所需的凭据查询/更新/连接测试接口：
- GET  /api/credentials          列出全部凭据组（密码掩码 + 来源标记）
- PUT  /api/credentials          按 key 更新用户名/密码（写 db/app.db credentials 表）
- POST /api/credentials/test     连接测试（ZTE UME 系 / eFlow 走真实登录，其余返回不支持）

存储实现见 backend/services/credential_store.py。
"""

import time
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backend.services.credential_store import (
    CREDENTIAL_GROUPS,
    _GROUP_INDEX,
    get_credential,
    get_effective,
    list_credentials,
    set_credential,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/credentials", tags=["credentials"])


def _is_en(request: Request) -> bool:
    """按 Accept-Language 判断请求语言（与前端 setApiLocale 保持一致）。"""
    return (request.headers.get("accept-language") or "").lower().startswith("en")


class CredentialUpdate(BaseModel):
    key: str
    username: str | None = None
    secret: str | None = None


class CredentialTestRequest(BaseModel):
    key: str


@router.get("")
def get_credentials(request: Request):
    """列出全部凭据组（密码掩码显示，标记来源 db/default/env）。

    按 Accept-Language 返回本地化组名与字段标签（en 时取 *_en 变体）。
    """
    return {"credentials": list_credentials("en" if _is_en(request) else "zh")}


@router.put("")
def update_credential(body: CredentialUpdate, request: Request):
    """更新指定 key 的用户名/密码。

    部分更新语义：字段为 None 或空串时保持原值不变；
    密码不回传明文，前端留空即表示不修改。
    """
    en = _is_en(request)
    if body.key not in _GROUP_INDEX:
        raise HTTPException(status_code=400, detail=(f"Unknown credential group: {body.key}" if en else f"未知凭据组: {body.key}"))
    if not body.username and not body.secret:
        raise HTTPException(status_code=400, detail=("Username and password cannot both be empty" if en else "用户名和密码不能同时为空"))
    cur_user, cur_secret = get_effective(body.key)
    new_user = body.username or cur_user
    new_secret = body.secret or cur_secret
    set_credential(body.key, new_user, new_secret)
    logger.info(f"[CRED] 凭据已更新: {body.key}")
    return {"status": "ok", "key": body.key, "message": ("Credentials saved, effective within 30s" if en else "凭据已保存，最迟 30 秒后生效")}


@router.get("/{key}/reveal")
def reveal_credential(key: str, request: Request):
    """返回指定凭据组当前生效的明文用户名/密码（环境变量 > 数据库 > 默认值）。"""
    en = _is_en(request)
    group = _GROUP_INDEX.get(key)
    if not group:
        raise HTTPException(status_code=400, detail=(f"Unknown credential group: {key}" if en else f"未知凭据组: {key}"))
    user, secret = get_credential(key, group["default_user"], group["default_secret"])
    return {"key": key, "username": user, "secret": secret}


@router.post("/test")
def test_credential(body: CredentialTestRequest, request: Request):
    """连接测试：使用当前生效的凭据尝试登录。

    支持 zte_ume / ipran_ume / ccn_ume / eflow（均为 ZTE OAuth2 RSA 登录）
    以及 rais（AES 加密密码 POST verify4web.serv 的直接鉴权）；
    其余组返回"暂不支持自动测试"。
    """
    en = _is_en(request)
    t0 = time.time()
    group = _GROUP_INDEX.get(body.key)
    if not group:
        raise HTTPException(status_code=400, detail=(f"Unknown credential group: {body.key}" if en else f"未知凭据组: {body.key}"))
    if not group.get("testable"):
        return {
            "status": "unsupported",
            "key": body.key,
            "message": ("Automatic connection test is not supported for this system. Save and check the next task run." if en
                        else "该系统暂不支持自动连接测试，请保存后观察下次任务执行结果"),
        }

    try:
        user, pwd = get_credential(
            group["key"], group["default_user"], group["default_secret"],
        )
        # RAIS 不是 ZTE OAuth2 RSA 登录，不能走 auth_manager._do_login：
        # 它走门户登录模块里的「直接鉴权」（AES-256-CBC 加密密码 POST
        # verify4web.serv 换 SSO token），复用它即可当作真实的登录测试。
        if body.key == "rais":
            from backend.services import portal_login_service as portal_svc
            try:
                acct, _token = portal_svc._rais_direct_auth(portal_svc.PORTALS["rais"])
                return {
                    "status": "ok",
                    "key": body.key,
                    "message": (f"Login succeeded (account {acct}, SSO token acquired)" if en
                                else f"登录成功（账号 {acct}，已获取 SSO token）"),
                    "elapsed": round(time.time() - t0, 2),
                }
            except Exception as e:
                logger.warning(f"[CRED] RAIS 连接测试失败: {e}")
                return {
                    "status": "fail",
                    "key": body.key,
                    "message": f"Login failed: {e}" if en else f"登录失败: {e}",
                    "elapsed": round(time.time() - t0, 2),
                }
        try:
            from backend.services.auth_manager import _do_login
        except ImportError:
            from auth_manager import _do_login
        result = _do_login(group["test_host"], group["test_port"], user, pwd)
        ok = bool(result.get("cookie"))
        return {
            "status": "ok" if ok else "fail",
            "key": body.key,
            "message": ("Login succeeded" if ok else "Login failed: no cookie received") if en
                      else ("登录成功" if ok else "登录失败：未获取到 Cookie"),
            "elapsed": round(time.time() - t0, 2),
        }
    except Exception as e:
        logger.warning(f"[CRED] 连接测试失败: {body.key}: {e}")
        return {
            "status": "fail",
            "key": body.key,
            "message": f"Login failed: {type(e).__name__}: {e}" if en else f"登录失败: {type(e).__name__}: {e}",
            "elapsed": round(time.time() - t0, 2),
        }
