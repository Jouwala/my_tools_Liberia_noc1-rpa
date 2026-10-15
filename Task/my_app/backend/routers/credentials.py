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


def _invalidate_sessions_for(key: str, *usernames: str) -> None:
    """改凭据后作废该组在**磁盘上**的会话缓存，使新账号即时生效。

    【2026-10-14 为什么需要】设置页（FastAPI 7038 进程）与任务是**不同进程**
    （worker_watchdog.py 以 subprocess 拉起 worker），改凭据无法直接清掉 worker
    进程内存里的会话。能触及的共享状态只有磁盘缓存，故在此按该组登记的
    test_host/test_port 删掉对应账号的缓存文件（invalidate_cache 只删本地文件、
    不发网络请求，安全）。

    usernames: 要作废的账号，**旧账号与新账号都要传**。改凭据的语义是「这个 key
    的旧会话一律作废」，旧账号那份缓存若不删，将来把凭据改回旧账号时会立即复用
    一份可能已在别处失效的会话。传 username 时 auth_manager 只删该账号那一份，
    不连坐同主机其它账号（多账号主机的既有约定，见 auth_manager._cache_file_path）。

    注意：这仍**不能**清除已在运行的 worker 内存里的旧会话 —— 那一层由
    eflow_api_client.ensure_login() 的账号比对负责（改凭据后 worker 下次调用
    即自动重登）。两处配合，改凭据后无需重启。

    仅供 eFlow / ZTE UME 系（走 auth_manager 的主机）生效；其余组无 test_host
    或不经 auth_manager，静默跳过。
    """
    group = _GROUP_INDEX.get(key) or {}
    host, port = group.get("test_host"), group.get("test_port")
    if not (host and port):
        return
    try:
        from backend.services.auth_manager import invalidate_cache
    except ImportError:
        from auth_manager import invalidate_cache
    # 去重后逐个账号清；空串跳过（invalidate_cache 传空会删该主机全部账号，非本意）。
    for u in dict.fromkeys(usernames):
        if not u:
            continue
        try:
            invalidate_cache(host, int(port), u)
            logger.info(f"[CRED] 已作废 {key} 在 {host}:{port} 账号 {u} 的会话缓存")
        except Exception as e:
            # 清缓存失败不该让「保存凭据」失败（凭据已落库，最迟 30s 生效）。
            logger.warning(f"[CRED] 作废 {key} 会话缓存失败（忽略）: {e}")


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
    # 旧账号与新账号的缓存都作废：改凭据 = 该 key 的旧会话一律失效。
    _invalidate_sessions_for(body.key, cur_user, new_user)
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

        # ★ 熔断冷却提示（2026-10-13）：若该主机正处于熔断冷却期，直接告知运维，
        #   而不是真的再去撞一次上游（那会刷新失败计数、拖延自动解锁）。
        #
        # ⚠ 措辞必须区分「本地熔断」与「上游锁定」（2026-10-13 修正）：
        #   本分支读的是 `get_lock_state()` —— 即本地熔断文件 `.locked_<host>_<port>.json`，
        #   **根本没有联系上游**。原实现把这种情况说成 "Account is locked upstream"
        #   （账号已被上游锁定），把「本地拦截中」误报成「上游状态」，导致运维以为
        #   上游仍在锁而无法判断到底是哪种（2026-10-13 排查时即被此文案误导）。
        #   现在明确拆开两件事：
        #     1) 当前动作：本地熔断冷却中，未向上游发起任何请求；
        #     2) 触发原因：熔断当时记录的上游报错原文（`reason`）—— 它才可能含
        #        `User has been locked (code=4)`；也可能只是 HTTP 400 等其它原因。
        #   同时把上游锁定的事实从 reason 里解析出来单列，避免再被"上游/本地"混淆。
        try:
            from backend.services.auth_manager import get_lock_state
        except ImportError:
            from auth_manager import get_lock_state
        _th, _tp = group.get("test_host"), group.get("test_port")
        if _th and _tp:
            # 传 user：熔断按 (host, port, username) 隔离，多账号主机上不能把
            # 别的账号的锁拿来报给本账号（2026-10-13）。
            _st = get_lock_state(_th, _tp, user or "")
            if _st:
                remain = max(0, int(float(_st.get("until", 0)) - time.time()))
                reason = str(_st.get("reason", ""))[:300]
                upstream_locked = ("User has been locked" in reason
                                   or "code=4" in reason or "code\":\"4" in reason)
                lock_note = (
                    " 上游确实报过「账号被锁」（code=4）。" if upstream_locked
                    else " 注意：熔断原因不一定是账号被锁（也可能是 HTTP 4xx/5xx 等瞬时错误）。"
                ) if not en else (
                    " Upstream did report an account lock (code=4)." if upstream_locked
                    else " Note: the trip reason may not be an account lock (could be a transient HTTP 4xx/5xx)."
                )
                return {
                    "status": "locked",
                    "key": body.key,
                    "message": ((
                        f"本地熔断冷却中：未向上游发起请求，{remain}s 后可再次尝试。"
                        f"熔断触发原因（记录于 {_st.get('locked_at', '未知时间')}）：{reason}。"
                        f"{lock_note}"
                    ) if not en else (
                        f"Local circuit breaker in cooldown: no upstream request was made; "
                        f"retry allowed in {remain}s. Trip reason (recorded at "
                        f"{_st.get('locked_at', 'unknown')}): {reason}.{lock_note}"
                    )),
                    "elapsed": round(time.time() - t0, 2),
                }

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
        # 终态错误（账号锁定 / 密码到期 / 上游要求验证码）明确标注，
        # 让界面能区分"再试一次可能就好"与"必须人工介入"（2026-10-13）。
        try:
            from backend.services.auth_manager import _is_terminal_login_error
        except ImportError:
            from auth_manager import _is_terminal_login_error
        _terminal = _is_terminal_login_error(str(e))
        return {
            "status": "fail",
            "key": body.key,
            "terminal": _terminal,
            "message": f"Login failed: {type(e).__name__}: {e}" if en else f"登录失败: {type(e).__name__}: {e}",
            "elapsed": round(time.time() - t0, 2),
        }
