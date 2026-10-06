"""最小鉴权助手（仅用于保护高危写/触发端点）。

策略：
- 来自本机回环地址(127.0.0.1 / ::1 / localhost) 的请求直接放行
  （前端、同机调度脚本、nginx 反代都走回环，不会受影响）。
- 远程请求必须携带正确的 `X-API-Token` 头，否则 403。
  Token 取自环境变量 MY_APP_API_TOKEN；未设置时远程请求一律拒绝。
这样无需在代码里硬编码新密钥，也不会破坏同机调用。

注意：uvicorn 以 `--proxy-headers` 启动，nginx 反代会带 `X-Forwarded-For`，
所以 `request.client.host` 拿到的是**真实客户端 IP**（局域网访问者不会显示成 127.0.0.1）。

===== XFF 伪造旁路修复（2026-10-06）=====
**背景（修复前的真实漏洞）**：
`request.client.host` 并非原始 socket 对端 —— uvicorn 的 ProxyHeadersMiddleware
在进入应用前就把它**改写**成了 `X-Forwarded-For` 里的值，而它的采信条件是
「TCP 直连方是 127.0.0.1」（forwarded_allow_ips 默认 "127.0.0.1"，
见 uvicorn/middleware/proxy_headers.py:35 与 uvicorn/config.py 的默认值）。

于是形成如下旁路：任何**能经由本机回环发起请求**的组件（本机 nginx、任何监听回环的
反向代理、SSRF 入口、以 127.0.0.1 为目标的本地脚本/浏览器扩展），只要自带一个
`X-Forwarded-For: 127.0.0.1`，就会被判定为「本机」——实测修复前：

    curl -H 'X-Forwarded-For: 127.0.0.1' http://127.0.0.1:7038/api/tasks/config/export
    → 200（应当 403/401）

受影响面不止 require_protected，还包括 `main.py` 的会话中间件
（`portal_auth.client_is_local(request)` → 直接放行，等于**整体鉴权旁路**）。

**修法**：本模块不再只看被改写过的 `request.client.host`，而是复刻门户侧
`server/auth/routes.ts:38` 的既有写法（那里早已显式防住同一威胁）：
  1. 先看 socket 对端是否为回环；
  2. 是回环时，**优先相信** `X-Real-IP` / `X-Forwarded-For` 里的真实客户端地址
     （nginx 在 `location /api/` 用 `proxy_set_header X-Real-IP $remote_addr`
     与 `$proxy_add_x_forwarded_for` 覆盖写入，客户端伪造的值会被替换掉）；
  3. 取到的地址仍属回环才算「本机」。

关键性质：**远程访客经 nginx 访问时，其真实 IP 会被还原出来，因而不再被当成本机**
——这正是修复要达成的效果；而真正同机的调用（不带这些头，或头里就是回环）行为不变。

为何不能只信 socket 对端：经 nginx 反代时**所有**请求的对端都是 127.0.0.1，
只看它会让 LAN 上的匿名请求全部拿到管理员身份。必须结合代理头还原真实来源。
"""
import ipaddress
import os
from fastapi import Request, Depends, HTTPException

API_TOKEN = os.environ.get("MY_APP_API_TOKEN", "")
_TRUSTED_LOCAL = {"127.0.0.1", "::1", "localhost"}


def _is_loopback(value: str) -> bool:
    """该地址字面量是否表示本机回环。

    比集合成员判断多覆盖 `::ffff:127.0.0.1`（IPv4-mapped IPv6）与整段 127.0.0.0/8；
    非 IP 字面量（如 localhost）退回原集合比较。
    """
    host = (value or "").strip()
    if not host:
        return False
    if host in _TRUSTED_LOCAL:
        return True
    # 去掉可能的端口（"127.0.0.1:1234" / "[::1]:1234"）
    if host.startswith("["):
        host = host[1:host.find("]")] if "]" in host else host.lstrip("[")
    elif host.count(":") == 1:
        host = host.rsplit(":", 1)[0]
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _forwarded_client(value: str) -> str:
    """取转发链里**最靠近客户端**的那个地址（XFF 是逗号分隔、代理逐个追加）。"""
    return value.split(",")[0].strip()


def client_is_local(request: Request) -> bool:
    """请求是否来自**真实的本机回环**（经 nginx 反代时按代理头还原真实来源）。

    见模块 docstring 的「XFF 伪造旁路修复」一节：判定必须基于代理头还原出的
    真实客户端地址，而不能只看已被 uvicorn 改写的 request.client.host。
    """
    peer = request.client.host if request.client else ""
    if not _is_loopback(peer):
        # 对端本身就不是回环：无需再看代理头（伪造的头不应提升权限）
        return False

    # 对端是回环 → 请求可能来自本机，也可能来自 nginx 转发的远程访客。
    # nginx 会用 $remote_addr / $proxy_add_x_forwarded_for 覆盖写入这两个头，
    # 因此这里读到的值是可信的；客户端自带的同名头已被 nginx 替换。
    real_ip = request.headers.get("X-Real-IP", "")
    if real_ip.strip():
        return _is_loopback(_forwarded_client(real_ip))

    xff = request.headers.get("X-Forwarded-For", "")
    if xff.strip():
        return _is_loopback(_forwarded_client(xff))

    # 无任何代理头：确认是同机直连（前端、调度脚本、看门狗）
    return True


def has_valid_token(request: Request) -> bool:
    """是否携带了正确的 X-API-Token（未配置该环境变量时恒为 False）。"""
    return bool(API_TOKEN) and request.headers.get("X-API-Token") == API_TOKEN


def is_privileged(request: Request) -> bool:
    """是否具备「本机 / 持令牌」写权限，判据与 require_protected 严格一致。

    供「先告诉前端能不能改」的场景复用（如界面配置接口返回 editable 标记），
    避免前端看到的权限与真正写入时的判定不一致。
    """
    return client_is_local(request) or has_valid_token(request)


def require_protected(request: Request):
    if is_privileged(request):
        return
    raise HTTPException(
        status_code=403,
        detail="Forbidden: 需从本机访问或携带正确的 X-API-Token 头",
    )
