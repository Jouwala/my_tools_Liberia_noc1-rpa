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

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.services.credential_store import (
    CREDENTIAL_GROUPS,
    _GROUP_INDEX,
    get_effective,
    list_credentials,
    set_credential,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/credentials", tags=["credentials"])


class CredentialUpdate(BaseModel):
    key: str
    username: str | None = None
    secret: str | None = None


class CredentialTestRequest(BaseModel):
    key: str


@router.get("")
def get_credentials():
    """列出全部凭据组（密码掩码显示，标记来源 db/default/env）"""
    return {"credentials": list_credentials()}


@router.put("")
def update_credential(body: CredentialUpdate):
    """更新指定 key 的用户名/密码。

    部分更新语义：字段为 None 或空串时保持原值不变；
    密码不回传明文，前端留空即表示不修改。
    """
    if body.key not in _GROUP_INDEX:
        raise HTTPException(status_code=400, detail=f"未知凭据组: {body.key}")
    if not body.username and not body.secret:
        raise HTTPException(status_code=400, detail="用户名和密码不能同时为空")
    cur_user, cur_secret = get_effective(body.key)
    new_user = body.username or cur_user
    new_secret = body.secret or cur_secret
    set_credential(body.key, new_user, new_secret)
    logger.info(f"[CRED] 凭据已更新: {body.key}")
    return {"status": "ok", "key": body.key, "message": "凭据已保存，最迟 30 秒后生效"}


@router.post("/test")
def test_credential(body: CredentialTestRequest):
    """连接测试：使用当前生效的凭据尝试登录。

    支持 zte_ume / ipran_ume / ccn_ume / eflow（均为 ZTE OAuth2 RSA 登录），
    其余组返回"暂不支持自动测试"。
    """
    t0 = time.time()
    group = _GROUP_INDEX.get(body.key)
    if not group:
        raise HTTPException(status_code=400, detail=f"未知凭据组: {body.key}")
    if not group.get("testable"):
        return {
            "status": "unsupported",
            "key": body.key,
            "message": "该系统暂不支持自动连接测试，请保存后观察下次任务执行结果",
        }

    try:
        from backend.services.credential_store import get_credential
        user, pwd = get_credential(
            group["key"], group["default_user"], group["default_secret"],
        )
        try:
            from backend.services.auth_manager import _do_login
        except ImportError:
            from auth_manager import _do_login
        result = _do_login(group["test_host"], group["test_port"], user, pwd)
        ok = bool(result.get("cookie"))
        return {
            "status": "ok" if ok else "fail",
            "key": body.key,
            "message": "登录成功" if ok else "登录失败：未获取到 Cookie",
            "elapsed": round(time.time() - t0, 2),
        }
    except Exception as e:
        logger.warning(f"[CRED] 连接测试失败: {body.key}: {e}")
        return {
            "status": "fail",
            "key": body.key,
            "message": f"登录失败: {type(e).__name__}: {e}",
            "elapsed": round(time.time() - t0, 2),
        }
