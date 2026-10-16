# -*- coding: utf-8 -*-
"""ZTE UME 网管（10.121.8.2）实时告警取数客户端。

## 上游契约（2026-10-16 实测打通，非推测）

这台网管是 **ZTE Keystone/Angular 门户**（`/ngportal`），与项目里 eFlow 那套
OAuth2 门户（`/api/oauth2/v1/*`）**不是同一套鉴权体系**，登录链路是三步：

1. `GET /api/v1.0/auth/rsa_public_key` → 拿 RSA 公钥（PEM）+ `Set-Cookie: CustomCookie=...`
2. 用公钥把**整个 Keystone 请求体** RSA(PKCS#1 v1.5) 加密，包成 `{"cipher": "<base64>"}`
   `POST /api/v1.0/auth/tokens`（`scope: "unscoped"`）→ 响应头 `X-Subject-Token: pro-...`
   —— 注意这个 token **不能直接**用于业务接口（实测一律 `smagent` 跳登录），
   它只是「未 scoped」凭据。
3. 项目级 token：`POST /api/v1.0/auth/project_scope_tokens`
   body `{auth:{identity:{methods:["token"],token:{id:"#UNSCOPETOKEN#"}},
        scope:{project:{id:<项目 UUID>}}}}`
   —— **`token.id` 是字面量占位符 `"#UNSCOPETOKEN#"`**（不是上一步的真实 token；
   门户前端源码 `getTokenByProjectId` 就是这么发的，2026-10-16 逐一试过：
   传真实 token 报 `postProjectToken fail`，传占位符 201 Created）。
   响应头 `X-Subject-Token` 即**项目 token**（形如 `pro-...`，长约 620 字符）。

业务接口 `POST /api/v2.0/fm/alarmsWithDetail` 需要**项目 token** + `Project-Id` 头，
否则 401 `insufficient permissions or token expired`。请求头中 `X-Auth-Token` 放项目 token。

## 告警响应结构（`{"total": N, "alarms": [ {...} ]}`）

每条告警关键字段（实测样本）：
    alarmId      —— 告警唯一 id（uuid），**去重主键用它**
    alarmCode    —— 告警码。**多形态**：既有 `"89069"` 这种短文本，也有
                    `"3305119853"` 这种长整数形态；比对时统一 `norm_alarm_code()`。
    level        —— 级别：`critical` / `major` / `warning`
    alarmObject  —— 站点/对象名（如 `LBR-MSC2-COMPUTER-02-01`）
    alarmTime    —— 发生时间（ISO8601，`2026-10-16T14:50:08Z`）
    description  —— 描述；suggestion —— 处置建议；location —— 位置
    confirmStatus—— 确认状态（`Unacknowledged` 等）
    projectName  —— 所属项目名

接口**支持服务端过滤**（`level` / `alarmCode` 等作为 body 字段），也支持
`pageSize` / `currentPage` 分页（响应 `total` 为总数）。本模块**做客户端分页遍历**，
不用服务端过滤 —— 因为告警码多形态（`89069` vs `3305119853.0`），SQL/服务端判等必漏，
与 `tt_alarm_trigger.py:49-51` 同一教训，统一在 Python 侧归一化后比对。

## 与 auth_manager 的关系

登录链路的第 1、2 步（RSA 公钥 + Keystone 密码换 token）沿用项目既有实现
`auth_manager.get_auth()`；第 3 步（项目 token）是本主机独有的，故在本模块内实现。
`probe` 探活函数也在这里（探业务端点，不是登录首页 —— 见 `get_auth` docstring 约束 1）。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from backend.services import auth_manager
from backend.services.rsa_util import rsa_encrypt_pem

logger = logging.getLogger("ume_alarm_client")

# ========== 上游坐标（换环境只改这里 / 环境变量） ==========
import os

HOST = os.environ.get("UME_ALARM_HOST", "10.121.8.2")
PORT = int(os.environ.get("UME_ALARM_PORT", "443"))

# 默认项目名。项目 token 必须绑定一个 OpenStack 项目；实测 `admin` 项目即可读全网告警。
DEFAULT_PROJECT_NAME = os.environ.get("UME_ALARM_PROJECT", "admin")

RSA_KEY_PATH = "/api/v1.0/auth/rsa_public_key"
TOKEN_PATH = "/api/v1.0/auth/tokens"
PROJECT_TOKEN_PATH = "/api/v1.0/auth/project_scope_tokens"
PROJECTS_PATH = "/ksportal/v3/auth/projects"
ALARM_PATH = "/api/v2.0/fm/alarmsWithDetail"

# 项目 token 请求里的字面量占位符（**不是**真实 token，见模块 docstring 第 3 步）
_UNSCOPE_PLACEHOLDER = "#UNSCOPETOKEN#"

# 单页默认条数 / 最多翻多少页（防静默截断：翻页到取满 total 或空页为止）
DEFAULT_PAGE_SIZE = 50
DEFAULT_MAX_PAGES = 40


def _runtime_credentials():
    """运行时获取凭据（环境变量 > 数据库 > 默认），支持设置页改密免重启生效。"""
    from backend.services.credential_store import get_credential
    return get_credential("ume_alarm")


def norm_alarm_code(value: Any) -> str:
    """告警码归一化：`'89069.0'` → `'89069'`，纯文本码原样返回。

    上游告警码多形态并存（短文本 `89069` 与长整数 `3305119853`），
    浮点尾巴（`.0`）会让字符串判等漏掉，故统一去掉末尾 `.0`。
    """
    text = "" if value is None else str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text


def _header_get(raw_headers: str, name: str) -> str:
    """从原始响应头里取一个头（大小写不敏感）。"""
    low = name.lower()
    for line in raw_headers.split("\r\n"):
        if line.lower().startswith(low + ":"):
            return line.split(": ", 1)[1].strip()
    return ""


def _alarm_headers(project_token: str, project_id: str, cookie: str) -> str:
    """业务接口请求头。缺 Project-Id 会 401，见模块 docstring。"""
    return (
        f"X-Auth-Token: {project_token}\r\n"
        f"Project-Id: {project_id}\r\n"
        f"Cookie: {cookie}\r\n"
        f"Content-Type: application/json\r\n"
        f"Front-End: ngportal\r\n"
        f"X-Requested-With: XMLHttpRequest\r\n"
        f"x-operation-mode: p3\r\n"
        f"Cache-Control: no-cache\r\n"
        f"Pragma: no-cache\r\n"
    )


def _list_projects(cookie: str, unscoped_token: str) -> List[Dict[str, Any]]:
    headers = (f"X-Auth-Token: {unscoped_token}\r\nCookie: {cookie}\r\n"
               f"Content-Type: application/json\r\n")
    status, _, _, body = auth_manager._http_request(
        HOST, PORT, "GET", PROJECTS_PATH, headers_extra=headers)
    if "200" not in status:
        raise RuntimeError(f"列项目失败：{status} {body[:200]!r}")
    return json.loads(body.decode("utf-8")).get("projects", [])


def _resolve_project_id(cookie: str, unscoped_token: str,
                        project_name: str) -> str:
    """按项目名解析项目 UUID；找不到就用同名回退，最后回退第一个项目。

    为什么不写死 UUID：本项目曾在多处硬编码上游 id，换机房/重建环境即失效
    （`AGENTS.md` 第三节原则 7）。这里按**名字**解析，名字可配（默认 `admin`）。
    """
    projects = _list_projects(cookie, unscoped_token)
    if not projects:
        raise RuntimeError("上游项目列表为空，无法解析 Project-Id")
    for p in projects:
        if str(p.get("name", "")).strip() == project_name.strip():
            return str(p["id"])
    # 名字没匹配上：回退第一个（记警告，不静默）
    logger.warning("[UMEAlarm] 项目名 %r 未找到，回退第一个项目 %r",
                   project_name, projects[0].get("name"))
    return str(projects[0]["id"])


def _keystone_login(user: str, pwd: str) -> Dict[str, str]:
    """本主机专属的 Keystone v3 登录：RSA 公钥 → 加密密码换未 scoped token。

    **不复用 `auth_manager.get_auth()`**：那套登的是 ZTE OAuth2 门户
    （`/api/oauth2/v1/authorize` + `/login/publickey`），本机没有这些端点
    （实测 404）。这里走 Keystone 专有链路，见模块 docstring 第 1、2 步。

    Returns:
        {"cookie": ..., "unscoped_token": ...}
    """
    # Step 1: RSA 公钥 + 会话 cookie
    status, _, raw, body = auth_manager._http_request(
        HOST, PORT, "GET", RSA_KEY_PATH)
    if "200" not in status:
        raise RuntimeError(f"取 RSA 公钥失败：{status}")
    cookie = _collect_set_cookies(raw)
    pem = json.loads(body.decode("utf-8")).get("key", "")
    pem_b64 = _pem_body(pem)
    if not pem_b64:
        raise RuntimeError("RSA 公钥为空")

    # Step 2: 整体加密 Keystone 请求体
    keystone = {
        "auth": {
            "identity": {
                "methods": ["password"],
                "password": {"user": {"name": user, "password": pwd,
                                      "domain": {"name": "Default"}}},
            },
            "scope": "unscoped",
        }
    }
    cipher = rsa_encrypt_pem(json.dumps(keystone), pem_b64)
    headers = (f"Cookie: {cookie}\r\nContent-Type: application/json\r\n"
               f"X-Requested-With: XMLHttpRequest\r\n")
    status, _, raw, resp = auth_manager._http_request(
        HOST, PORT, "POST", TOKEN_PATH, headers_extra=headers,
        body=json.dumps({"cipher": cipher}))
    if "200" not in status and "201" not in status:
        raise RuntimeError(f"Keystone 登录失败：{status} {resp[:200]!r}")
    token = _header_get(raw, "X-Subject-Token")
    if not token:
        raise RuntimeError("登录成功但响应无 X-Subject-Token")
    # 合并登录过程中新下发的 cookie（如 tpSID-*）
    cookie = _merge_cookie(cookie, _collect_set_cookies(raw))
    return {"cookie": cookie, "unscoped_token": token}


def _pem_body(pem: str) -> str:
    """PEM（含头尾）→ 裸 Base64（`rsa_encrypt_pem` 要的是这种）。"""
    return re.sub(r"-----[A-Z ]+-----", "", pem or "").replace("\n", "").replace("\r", "").strip()


def _collect_set_cookies(raw_headers: str) -> str:
    """把响应的所有 Set-Cookie（取 name=value）拼成请求用 Cookie 头。"""
    out = []
    for line in raw_headers.split("\r\n"):
        if line.lower().startswith("set-cookie:"):
            out.append(line.split(": ", 1)[1].split(";")[0])
    return "; ".join(out)


def _merge_cookie(a: str, b: str) -> str:
    """合并两个 Cookie 串（同名后者覆盖前者）。"""
    merged: Dict[str, str] = {}
    for blob in (a, b):
        for part in (blob or "").split(";"):
            part = part.strip()
            if part and "=" in part:
                merged[part.split("=", 1)[0]] = part
    return "; ".join(merged.values())


# ========== 会话缓存（2026-10-16 修复「每分钟重登触发上游 gvcode 验证码」） ==========
#
# 背景：本任务每分钟跑一轮。若每轮都做一次「RSA + 密码」完整登录，等于对上游
# 每天 1440 次密码登录 —— 上游的防滥用策略会返回
# `401 {"error":{"code":401,"gvcode...}}`（要求图形验证码），任务随即整轮失败。
#
# 因此缓存会话（cookie + 项目 token），复用前先用业务端点**探活**：
#   * 探活通过 → 直接用缓存 token（不碰密码登录，上游无感）；
#   * 探活失败（token 过期 / 被踢） → 作废缓存、真实重登一次。
# 这与 `auth_manager.get_auth` 的「缓存命中先探活、探不通就地重登」同源
# （见其 docstring 约束 1：探活必须探**业务端点**，不能探登录首页）。
#
# 缓存是**进程内**的：worker 进程常驻，所以每分钟一轮里只有 token 真过期时才登录。
_SESSION_CACHE: Dict[str, Dict[str, Any]] = {}


def login(project_name: Optional[str] = None,
          force_refresh: bool = False) -> Dict[str, str]:
    """完整登录：Keystone 密码换 token → 项目 token（带进程内缓存 + 探活复用）。

    Returns:
        {"project_token": ..., "project_id": ..., "cookie": ...}
        `project_token` 可直接用于 `alarmsWithDetail`。

    `force_refresh=True` 时跳过缓存直接重登（用于业务调用 401 后的恢复）。
    """
    user, pwd = _runtime_credentials()
    project_name = project_name or DEFAULT_PROJECT_NAME

    if not force_refresh:
        cached = _SESSION_CACHE.get(project_name)
        if cached and _session_usable(cached):
            return cached
        if cached:
            logger.info("[UMEAlarm] 缓存会话探活失败，重新登录（project=%s）", project_name)
            _SESSION_CACHE.pop(project_name, None)

    auth = _keystone_login(user, pwd)
    cookie = auth["cookie"]
    unscoped = auth["unscoped_token"]
    project_id = _resolve_project_id(cookie, unscoped, project_name)
    project_token = _fetch_project_token(cookie, unscoped, project_id)
    session = {"project_token": project_token, "project_id": project_id,
               "cookie": cookie}
    _SESSION_CACHE[project_name] = session
    return session


def _session_usable(session: Dict[str, str]) -> bool:
    """探活：用缓存 token 打一次业务端点，200 即视为可用。"""
    try:
        headers = _alarm_headers(session["project_token"], session["project_id"],
                                 session["cookie"])
        status, _, _, _ = auth_manager._http_request(
            HOST, PORT, "POST", ALARM_PATH, headers_extra=headers,
            body=json.dumps({"lang": "en", "pageSize": 1, "currentPage": 1}))
        return "200" in status
    except Exception:  # noqa: BLE001
        logger.warning("[UMEAlarm] 缓存会话探活异常（按不可用处理）", exc_info=True)
        return False


def _clear_session_cache() -> None:
    """清空进程内会话缓存（测试与排障用）。"""
    _SESSION_CACHE.clear()


def _fetch_project_token(cookie: str, unscoped_token: str,
                         project_id: str) -> str:
    """用未 scoped token 换项目 token（`#UNSCOPETOKEN#` 占位符，见 docstring）。

    请求头里 `X-Auth-Token` 放**未 scoped token**（实测 `X-Auth-Token` /
    `x-auth-token` 两种写法都 201 Created）；body 的 `token.id` 却是字面量
    `#UNSCOPETOKEN#`，两者不是同一个值，别混。
    """
    body = json.dumps({
        "auth": {
            "identity": {"methods": ["token"],
                         "token": {"id": _UNSCOPE_PLACEHOLDER}},
            "scope": {"project": {"id": project_id}},
        }
    })
    headers = (f"X-Auth-Token: {unscoped_token}\r\n"
               f"Cookie: {cookie}\r\nContent-Type: application/json\r\n"
               f"X-Requested-With: XMLHttpRequest\r\n")
    status, _, raw, resp = auth_manager._http_request(
        HOST, PORT, "POST", PROJECT_TOKEN_PATH, headers_extra=headers, body=body)
    token = _header_get(raw, "X-Subject-Token")
    if "201" not in status and "200" not in status:
        raise RuntimeError(f"换项目 token 失败：{status} {resp[:200]!r}")
    if not token:
        raise RuntimeError("换项目 token 成功但响应无 X-Subject-Token")
    return token


def fetch_alarms(page_size: int = DEFAULT_PAGE_SIZE,
                 max_pages: int = DEFAULT_MAX_PAGES,
                 project_name: Optional[str] = None) -> Dict[str, Any]:
    """拉取当前所有未清除告警（客户端分页遍历）。

    Returns:
        {"alarms": [归一化告警行], "total": int, "fetched": int,
         "truncated": bool, "pages": int}

    `truncated=True` 表示翻到 max_pages 仍未取满 total（**必须显式暴露**，
    不能静默截断 —— `AGENTS.md` 第三节第 6 条与下钻铁律同款要求）。
    """
    project_name = project_name or DEFAULT_PROJECT_NAME
    session = login(project_name)

    # 401 恢复：缓存 token 可能恰在探活之后、本次调用之前过期。重登一次再试
    # （force_refresh 跳过缓存），仍失败才抛错 —— 避免把一个已死的缓存 token
    # 反复用到整轮失败。
    for attempt in range(2):
        try:
            return _fetch_pages(session, page_size, max_pages)
        except _AuthExpired:
            if attempt == 1:
                raise
            logger.info("[UMEAlarm] 业务调用 401，重登后重试（project=%s）", project_name)
            session = login(project_name, force_refresh=True)
    raise RuntimeError("不可达")  # pragma: no cover


class _AuthExpired(Exception):
    """业务端点返回 401（token 过期 / 被踢），由 fetch_alarms 捕获后重登重试。"""


def _fetch_pages(session: Dict[str, str], page_size: int,
                 max_pages: int) -> Dict[str, Any]:
    """按会话分页拉全量告警；401 时抛 `_AuthExpired` 交由上层重登。"""
    headers = _alarm_headers(session["project_token"], session["project_id"],
                             session["cookie"])
    alarms: List[Dict[str, Any]] = []
    total = 0
    pages = 0
    for page in range(1, max_pages + 1):
        body = json.dumps({"lang": "en", "pageSize": page_size,
                           "currentPage": page})
        status, _, _, resp = auth_manager._http_request(
            HOST, PORT, "POST", ALARM_PATH, headers_extra=headers, body=body)
        if "401" in status:
            raise _AuthExpired(f"401 {resp[:120]!r}")
        if "200" not in status:
            raise RuntimeError(
                f"拉告警失败（第 {page} 页）：{status} {resp[:200]!r}")
        data = json.loads(resp.decode("utf-8"))
        total = int(data.get("total") or 0)
        batch = data.get("alarms") or []
        pages = page
        for raw in batch:
            alarms.append(normalize_alarm(raw))
        if not batch or len(alarms) >= total:
            break
    # 翻到上限仍未取满 total = 被截断（显式暴露，不静默）
    return {"alarms": alarms, "total": total, "fetched": len(alarms),
            "truncated": pages >= max_pages and len(alarms) < total,
            "pages": pages}


def normalize_alarm(raw: Dict[str, Any]) -> Dict[str, Any]:
    """上游告警行 → 内部归一化行（字段名收敛在此，别处不碰上游字段名）。"""
    code = norm_alarm_code(raw.get("alarmCode"))
    obj = str(raw.get("alarmObject") or "").strip()
    inv = _parse_iso_local(raw.get("alarmTime") or raw.get("serverTime"))
    return {
        "alarm_id": str(raw.get("alarmId") or "").strip(),
        "alarm_code": code,
        "level": str(raw.get("level") or "").strip().lower(),
        "object": obj,
        "occur_time": inv,
        "description": str(raw.get("description") or "").strip(),
        "suggestion": str(raw.get("suggestion") or "").strip(),
        "location": str(raw.get("location") or "").strip(),
        "confirm_status": str(raw.get("confirmStatus") or "").strip(),
        "project_name": str(raw.get("projectName") or "").strip(),
    }


def _parse_iso_local(value: Any) -> str:
    """ISO8601（`2026-10-16T14:50:08Z`）→ 本地 `%Y-%m-%d %H:%M:%S` 文本。

    上游给 UTC（Z 后缀），统一转成本机本地时间，与项目其它告警表口径一致。
    """
    text = "" if value is None else str(value).strip()
    if not text:
        return ""
    from datetime import datetime, timezone
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except Exception:  # noqa: BLE001
        return text
